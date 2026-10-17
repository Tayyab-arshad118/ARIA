"""Local lexical sentiment and reference selection; XTTS has no native emotion control."""
import json
import re
from uuid import uuid4

import anyio
from sqlalchemy import delete, select

from ..db import AudioCache, EmotionReference, PhraseAudio
from .audio_utils import prepare_reference
from .errors import ServiceError
from .voice_store import validate_latents

TAGS = ("neutral", "happy", "sad", "calm", "angry")
LEXICON = {
    "happy": {"خوش", "خوشی", "شکریہ", "محبت", "مبارک", "اچھا", "happy", "khush", "shukriya"},
    "sad": {"اداس", "درد", "تکلیف", "پریشان", "غم", "sad", "udas", "dard"},
    "calm": {"آرام", "سکون", "آہستہ", "calm", "aram", "ahista"},
    "angry": {"غصہ", "ناراض", "angry", "gussa", "naraz"},
}


def classify(text):
    words = re.findall(r"[\w]+", text.lower())
    scores = dict.fromkeys(LEXICON, 0)
    for index, word in enumerate(words):
        for label, vocabulary in LEXICON.items():
            if word in vocabulary:
                negated = any(w in {"نہیں", "نہ", "nahi", "nahin", "not"} for w in words[max(0, index - 2):index + 3])
                if not negated:
                    scores[label] += 1
    winner = max(scores, key=scores.get)
    return winner if scores[winner] else "neutral"


class EmotionService:
    def __init__(self, settings, db, cipher, gpu, liveness):
        self.settings, self.db, self.cipher, self.gpu, self.liveness = settings, db, cipher, gpu, liveness

    def fingerprint(self, voice_id, text):
        if not self.settings.emotion_enabled:
            return "emotion-off"
        label = classify(text)
        with self.db.session() as session:
            row = session.get(EmotionReference, (voice_id, label))
            revision = row.revision if row and row.model_version == self.settings.model_version else "base"
        return [label, revision, self.settings.emotion_speed_delta, self.settings.emotion_temperature_delta, "lexicon-v1"]

    def select(self, voice_id, text, latents, speed):
        label = classify(text) if self.settings.emotion_enabled else "neutral"
        selected = False
        if self.settings.emotion_enabled:
            with self.db.session() as session:
                row = session.get(EmotionReference, (voice_id, label))
                if row and row.model_version == self.settings.model_version:
                    latents = json.loads(self.cipher.decrypt(row.latents))
                    selected = True
        direction = {"neutral": 0, "happy": 1, "sad": -1, "calm": -1, "angry": 1}[label]
        adjusted_speed = min(2.0, max(0.5, speed + direction * self.settings.emotion_speed_delta))
        temperature = min(1.5, max(0.1, self.settings.default_temperature + direction * self.settings.emotion_temperature_delta))
        return latents, adjusted_speed, temperature, label, selected

    def list(self, voice_id):
        with self.db.session() as session:
            return [{"emotion": row.emotion, "model_version": row.model_version,
                     "needs_reenrollment": row.model_version != self.settings.model_version}
                    for row in session.scalars(select(EmotionReference).where(EmotionReference.voice_id == voice_id))]

    async def enroll(self, voice_id, label, raw):
        if not self.settings.emotion_enabled:
            raise ServiceError(409, "Emotion references are disabled")
        prepared = await anyio.to_thread.run_sync(prepare_reference, raw, self.settings)
        if self.settings.security_mode != "off":
            expected, _ = self.liveness.reference(voice_id)
            embedding = await self.liveness.enrollment_embedding(prepared)
            if self.liveness.similarity(expected, embedding) < self.settings.liveness_speaker_threshold:
                raise ServiceError(403, "Emotion reference does not match the enrolled speaker")
        latents = await self.gpu.latents(prepared)
        validate_latents(latents)
        with self.db.session.begin() as session:
            session.merge(EmotionReference(voice_id=voice_id, emotion=label,
                latents=self.cipher.encrypt(json.dumps(latents).encode()),
                raw_audio=self.cipher.encrypt(raw) if self.settings.keep_raw_audio else None,
                model_version=self.settings.model_version, revision=str(uuid4())))
            session.execute(delete(AudioCache).where(AudioCache.voice_id == voice_id))
            session.execute(delete(PhraseAudio).where(PhraseAudio.voice_id == voice_id))
        return {"voice_id": voice_id, "emotion": label, "model_version": self.settings.model_version}

    def delete(self, voice_id, label):
        with self.db.session.begin() as session:
            row = session.get(EmotionReference, (voice_id, label))
            if row is None:
                raise ServiceError(404, "Emotion reference not found")
            session.delete(row)
            session.execute(delete(AudioCache).where(AudioCache.voice_id == voice_id))
            session.execute(delete(PhraseAudio).where(PhraseAudio.voice_id == voice_id))
