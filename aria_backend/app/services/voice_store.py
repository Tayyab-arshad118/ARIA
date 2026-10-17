import base64
import io
import json
import math
from uuid import uuid4

import numpy as np
from sqlalchemy import delete, select

from ..db import Voice, AudioCache, TextCache, PhraseAudio, SpokenHistory, VerificationProfile, EmotionReference
from .audio_utils import prepare_reference
from .errors import ServiceError


def validate_latents(values):
    try:
        for key in ("gpt_cond_latent", "speaker_embedding"):
            encoded = values[key]
            if not isinstance(encoded, str) or len(encoded) > 2 * 1024 * 1024:
                raise ValueError()
            raw = base64.b64decode(encoded, validate=True)
            stream = io.BytesIO(raw)
            version = np.lib.format.read_magic(stream)
            reader = {(1, 0): np.lib.format.read_array_header_1_0,
                      (2, 0): np.lib.format.read_array_header_2_0}.get(version)
            if not reader:
                raise ValueError()
            shape, order, dtype = reader(stream)
            if (len(shape) != 3 or shape[0] != 1 or any(d <= 0 for d in shape)
                    or dtype.kind != "f" or dtype.itemsize != 4 or order
                    or math.prod(shape) * 4 != len(raw) - stream.tell()):
                raise ValueError()
            if not np.isfinite(np.load(io.BytesIO(raw), allow_pickle=False)).all():
                raise ValueError()
    except (KeyError, ValueError, TypeError, EOFError, OSError):
        raise ServiceError(502, "Colab returned invalid voice latents") from None


class VoiceStore:
    def __init__(self, settings, db, cipher, gpu, liveness=None):
        self.settings, self.db, self.cipher, self.gpu = settings, db, cipher, gpu
        self.liveness = liveness

    def profile(self, voice):
        with self.db.session() as session:
            verification = session.get(VerificationProfile, voice.id)
            ready = bool(verification and verification.model_version == self.settings.liveness_model_version)
        return {"id": voice.id, "name": voice.name, "created_at": voice.created_at,
                "model_version": voice.model_version,
                "needs_reenrollment": voice.model_version != self.settings.model_version, "verification_ready": ready}

    def list(self):
        with self.db.session() as session:
            voices = list(session.scalars(select(Voice).order_by(Voice.created_at, Voice.id)))
            default = next((voice.id for voice in voices if voice.model_version == self.settings.model_version), None)
            return [{**self.profile(voice), "is_default": voice.id == default} for voice in voices]

    async def enroll(self, raw, name):
        import anyio
        prepared = await anyio.to_thread.run_sync(prepare_reference, raw, self.settings)
        embedding = (await self.liveness.enrollment_embedding(prepared)
                     if self.settings.security_mode != "off" and self.liveness else None)
        latents = await self.gpu.latents(prepared)
        validate_latents(latents)
        voice = Voice(id=str(uuid4()), name=name, model_version=self.settings.model_version,
                      latents=self.cipher.encrypt(json.dumps(latents).encode()),
                      raw_audio=self.cipher.encrypt(raw) if self.settings.keep_raw_audio else None)
        with self.db.session.begin() as session:
            session.add(voice)
            session.flush()
            if embedding is not None:
                session.add(VerificationProfile(voice_id=voice.id,
                    embedding=self.cipher.encrypt(json.dumps(embedding).encode()),
                    model_version=self.settings.liveness_model_version, revision=str(uuid4())))
            result = self.profile(voice)
            result["verification_ready"] = embedding is not None
        return result

    def get(self, voice_id):
        with self.db.session() as session:
            if voice_id == "default":
                voice = session.scalar(select(Voice).where(Voice.model_version == self.settings.model_version)
                                       .order_by(Voice.created_at, Voice.id).limit(1))
                if voice is None:
                    voice = session.scalar(select(Voice).order_by(Voice.created_at, Voice.id).limit(1))
            else:
                voice = session.get(Voice, voice_id)
            if voice is None:
                raise ServiceError(404, "Voice not found; enroll a voice first")
            if voice.model_version != self.settings.model_version:
                raise ServiceError(409, "This voice belongs to another model; re-enroll it")
            return voice.id, json.loads(self.cipher.decrypt(voice.latents))

    def delete(self, voice_id):
        with self.db.session.begin() as session:
            voice = session.get(Voice, voice_id)
            if voice is None:
                raise ServiceError(404, "Voice not found")
            session.execute(delete(AudioCache).where(AudioCache.voice_id == voice_id))
            session.execute(delete(PhraseAudio).where(PhraseAudio.voice_id == voice_id))
            session.execute(delete(SpokenHistory).where(SpokenHistory.voice_id == voice_id))
            session.execute(delete(VerificationProfile).where(VerificationProfile.voice_id == voice_id))
            session.execute(delete(EmotionReference).where(EmotionReference.voice_id == voice_id))
            session.delete(voice)

    def delete_all(self):
        with self.db.session.begin() as session:
            for table in (EmotionReference, VerificationProfile, PhraseAudio, SpokenHistory, AudioCache, TextCache, Voice):
                session.execute(delete(table))
