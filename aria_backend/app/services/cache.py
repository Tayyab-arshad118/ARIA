import hashlib
import json

from sqlalchemy import delete, select

from ..db import AudioCache


class AudioCacheService:
    def __init__(self, settings, db, cipher):
        self.settings, self.db, self.cipher = settings, db, cipher
        self.emotions = None

    def key(self, voice_id, text, speed, language="ur"):
        # Include processing/sampling defaults so changing configuration never reuses stale sound.
        return hashlib.sha256(json.dumps([voice_id, text, speed, self.settings.model_version,
            self.settings.default_temperature, self.settings.output_sample_rate, self.settings.silence_ms,
            self.settings.target_dbfs, self.settings.chunk_max_chars,
            self.emotions.fingerprint(voice_id, text) if self.emotions else "emotion-off",
            language, self.settings.language_aliases.get(language, language), self.settings.lang_tag,
            "audio-v3"], ensure_ascii=False).encode()).hexdigest()

    def get(self, key):
        with self.db.session() as session:
            item = session.get(AudioCache, key)
            return self.cipher.decrypt(item.audio) if item else None

    def put(self, key, voice_id, audio):
        if not self.settings.audio_cache_entries:
            return
        with self.db.session.begin() as session:
            session.merge(AudioCache(key=key, voice_id=voice_id, audio=self.cipher.encrypt(audio)))
            stale = list(session.scalars(select(AudioCache.key).order_by(AudioCache.created_at.desc())
                                        .offset(self.settings.audio_cache_entries)))
            if stale:
                session.execute(delete(AudioCache).where(AudioCache.key.in_(stale)))
