import hashlib
import json
from uuid import uuid4

from sqlalchemy import delete, func, select

from ..db import Phrase, PhraseAudio, RuntimeSetting, SpokenHistory
from ..db.database import timestamp
from .errors import ServiceError
from .urdu_normalizer import normalize_urdu
from .languages import preserve_text

CATEGORIES = ("needs", "medical", "family", "greetings", "custom")


class PhraseStore:
    def __init__(self, settings, db, cipher, cache):
        self.settings, self.db, self.cipher, self.cache = settings, db, cipher, cache

    def pack(self, content):
        return self.cipher.encrypt(json.dumps(content, ensure_ascii=False).encode())

    def unpack(self, phrase):
        return {"id": phrase.id, **json.loads(self.cipher.decrypt(phrase.content)),
                "favorite": phrase.favorite, "last_used": phrase.last_used, "uses": phrase.uses}

    def seed(self):
        with self.db.session.begin() as session:
            if session.get(RuntimeSetting, "phrases_seeded"):
                return
            items = json.loads(self.settings.phrase_seed_path.read_text(encoding="utf-8"))
            if len(items) > self.settings.phrase_max_count:
                raise ValueError("Phrase seed exceeds PHRASE_MAX_COUNT")
            for item in items:
                if item["category"] not in CATEGORIES or not item["roman"].strip() or not item["urdu"].strip():
                    raise ValueError("Invalid phrase seed")
                session.add(Phrase(id=item["id"], content=self.pack({k: item[k] for k in ("roman", "urdu", "category")})))
            session.add(RuntimeSetting(key="phrases_seeded", value=self.cipher.encrypt(b"1")))

    def all(self):
        with self.db.session() as session:
            return [self.unpack(p) for p in session.scalars(select(Phrase).order_by(Phrase.created_at, Phrase.id))]

    def get(self, identifier):
        with self.db.session() as session:
            phrase = session.get(Phrase, identifier)
            if phrase is None:
                raise ServiceError(404, "Phrase not found")
            return self.unpack(phrase)

    def create(self, content):
        with self.db.session.begin() as session:
            if session.scalar(select(func.count()).select_from(Phrase)) >= self.settings.phrase_max_count:
                raise ServiceError(409, "Phrase bank is full; delete a phrase first")
            item = Phrase(id=str(uuid4()), content=self.pack(content))
            session.add(item)
            session.flush()
            return self.unpack(item)

    def update(self, identifier, changes):
        with self.db.session.begin() as session:
            phrase = session.get(Phrase, identifier)
            if phrase is None:
                raise ServiceError(404, "Phrase not found")
            if "favorite" in changes:
                phrase.favorite = changes["favorite"]
            content = json.loads(self.cipher.decrypt(phrase.content))
            if any(key in changes for key in ("roman", "urdu", "category")):
                content.update({key: changes[key] for key in ("roman", "urdu", "category") if key in changes})
                phrase.content = self.pack(content)
                session.execute(delete(PhraseAudio).where(PhraseAudio.phrase_id == identifier))
            session.flush()
            return self.unpack(phrase)

    def delete(self, identifier):
        with self.db.session.begin() as session:
            phrase = session.get(Phrase, identifier)
            if phrase is None:
                raise ServiceError(404, "Phrase not found")
            session.execute(delete(PhraseAudio).where(PhraseAudio.phrase_id == identifier))
            session.delete(phrase)

    def reset(self):
        with self.db.session.begin() as session:
            session.execute(delete(PhraseAudio).where(PhraseAudio.voice_id != "aria_builtin"))
            seed_ids = [p["id"] for p in json.loads(self.settings.phrase_seed_path.read_text(encoding="utf-8"))]
            session.execute(delete(PhraseAudio).where(PhraseAudio.phrase_id.not_in(seed_ids)))
            for table in (Phrase, SpokenHistory):
                session.execute(delete(table))
            session.execute(delete(RuntimeSetting).where(RuntimeSetting.key == "phrases_seeded"))
        self.seed()

    def key(self, phrase, voice_id, speed, language="ur", emotion="neutral"):
        text = preserve_text(phrase["urdu"] if language == "ur" else phrase["display_text"])
        audio_key = self.cache.key(voice_id, text, speed, language, emotion)
        digest = hashlib.sha256((phrase["id"] + ":" + audio_key).encode()).hexdigest()
        return language + ":" + emotion + ":" + digest

    def audio(self, key):
        with self.db.session() as session:
            row = session.get(PhraseAudio, key)
            return self.cipher.decrypt(row.audio) if row else None

    def cached_keys(self, voice_id):
        with self.db.session() as session:
            return set(session.scalars(select(PhraseAudio.key).where(PhraseAudio.voice_id == voice_id)))

    def has_audio(self, key):
        with self.db.session() as session:
            return session.scalar(select(PhraseAudio.key).where(PhraseAudio.key == key)) is not None

    def put_audio(self, phrase, voice_id, speed, audio, language="ur", emotion="neutral"):
        key = self.key(phrase, voice_id, speed, language, emotion)
        with self.db.session.begin() as session:
            session.merge(PhraseAudio(key=key, phrase_id=phrase["id"], voice_id=voice_id, speed=speed,
                                      audio=self.cipher.encrypt(audio)))
            session.flush()
            # Keep the current default-speed clip plus two most recent custom-speed clips per pair.
            rows = list(session.scalars(select(PhraseAudio).where(PhraseAudio.phrase_id == phrase["id"],
                PhraseAudio.voice_id == voice_id,
                PhraseAudio.key.like(language + ":" + emotion + ":%")
                ).order_by(PhraseAudio.created_at.desc())))
            retained_custom = 0
            default_key = self.key(phrase, voice_id, self.settings.default_speed, language, emotion)
            for row in rows:
                if row.speed == self.settings.default_speed:
                    if row.key != default_key:
                        session.delete(row)
                elif retained_custom < 2:
                    retained_custom += 1
                else:
                    session.delete(row)

    def mark_used(self, identifier):
        with self.db.session.begin() as session:
            phrase = session.get(Phrase, identifier)
            if phrase:
                phrase.last_used = timestamp()
                phrase.uses += 1

    def list(self, voice_id=None, speed=None, category=None, favorites=False, recent=False):
        speed = self.settings.default_speed if speed is None else speed
        keys = self.cached_keys(voice_id) if voice_id else set()
        rows = [p for p in self.all() if (not category or p["category"] == category)
                and (not favorites or p["favorite"]) and (not recent or p["last_used"])]
        if recent:
            rows.sort(key=lambda p: p["last_used"], reverse=True)
            rows = rows[:20]
        return [{**p, "cached": self.key(p, voice_id, speed) in keys if voice_id else False} for p in rows]
