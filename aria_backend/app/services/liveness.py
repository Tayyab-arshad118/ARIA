"""Best-effort speech challenge plus ECAPA match, not a foolproof deepfake detector."""
from dataclasses import dataclass
from difflib import SequenceMatcher
import hashlib
import json
import secrets
import threading
import time
import unicodedata

import anyio
import numpy as np

from ..db import VerificationProfile
from .audio_utils import resample
from .errors import ServiceError
from .safety_audio import decode_wav
from .urdu_normalizer import normalize_urdu

WORDS = "پانی کتاب گھر دروازہ کھڑکی کرسی بستر چاند سورج پھول باغ بارش ہوا دن رات صبح شام دوست بھائی بہن راستہ بازار روشنی خوشی".split()


def canonical(text):
    return "".join(c for c in normalize_urdu(text) if not c.isspace() and not unicodedata.category(c).startswith("P"))


class VerificationEngine:
    def __init__(self, settings):
        self.settings = settings
        self.speaker = self.asr = None

    def embedding(self, samples, sr):
        import torch
        if self.speaker is None:
            path = self.settings.liveness_speaker_path
            if not path.is_dir() or not (path / "hyperparams.yaml").is_file():
                raise RuntimeError("Local ECAPA model missing")
            from speechbrain.inference.speaker import EncoderClassifier
            from speechbrain.utils.fetching import LocalStrategy
            torch.set_num_threads(self.settings.safety_cpu_threads)
            self.speaker = EncoderClassifier.from_hparams(source=str(path),
                savedir=str(self.settings.safety_cache_dir / "ecapa"),
                overrides={"pretrained_path": str(path)}, run_opts={"device": "cpu"},
                local_strategy=LocalStrategy.COPY)
        audio = torch.from_numpy(resample(samples, sr, 16000)).unsqueeze(0)
        with torch.no_grad():
            result = self.speaker.encode_batch(audio).reshape(-1).cpu().numpy()
        return result

    def transcript(self, samples, sr):
        if self.asr is None:
            if not self.settings.liveness_whisper_path.is_dir():
                raise RuntimeError("Local Whisper model missing")
            from faster_whisper import WhisperModel
            self.asr = WhisperModel(str(self.settings.liveness_whisper_path), device="cpu", compute_type=self.settings.liveness_compute_type,
                cpu_threads=self.settings.safety_cpu_threads, num_workers=1, local_files_only=True)
        segments, _ = self.asr.transcribe(resample(samples, sr, 16000), language=self.settings.liveness_language,
                                         beam_size=self.settings.liveness_beam_size, vad_filter=self.settings.liveness_vad_filter)
        return " ".join(segment.text for segment in segments)


@dataclass
class Challenge:
    voice_id: str
    model_version: str
    reference_revision: str
    phrase: str
    words: tuple
    expires: float


class Liveness:
    def __init__(self, settings, db, cipher, engine=None, clock=time.monotonic):
        self.settings, self.db, self.cipher = settings, db, cipher
        self.engine = engine or VerificationEngine(settings)
        self.clock = clock
        self.lock = threading.Lock()
        self.challenges, self.sessions = {}, {}

    def reference(self, voice_id):
        with self.db.session() as session:
            row = session.get(VerificationProfile, voice_id)
            if row is None or row.model_version != self.settings.liveness_model_version:
                raise ServiceError(409, "Re-enroll this voice with verification enabled before using liveness checks")
            return np.asarray(json.loads(self.cipher.decrypt(row.embedding)), dtype=np.float32), row.revision

    def _embedding(self, raw):
        samples, sr = decode_wav(raw, self.settings.max_reference_seconds, self.settings.min_reference_seconds)
        with self.lock:
            try:
                result = np.asarray(self.engine.embedding(samples, sr), dtype=np.float32)
                if result.ndim != 1 or not 1 <= len(result) <= 4096 or not np.isfinite(result).all() or np.linalg.norm(result) == 0:
                    raise ValueError()
                return result.tolist()
            except Exception:
                raise ServiceError(503, "Speaker verification unavailable; install dependencies and local ECAPA weights") from None

    async def enrollment_embedding(self, raw):
        return await anyio.to_thread.run_sync(self._embedding, raw)

    def prune(self):
        now = self.clock()
        self.challenges = {key: c for key, c in self.challenges.items() if c.expires > now}
        self.sessions = {key: s for key, s in self.sessions.items() if s["expires"] > now}

    def issue(self, voice_id):
        if self.settings.security_mode == "off":
            raise ServiceError(409, "Liveness verification is disabled")
        _, revision = self.reference(voice_id)
        self.prune()
        if len(self.challenges) >= self.settings.liveness_max_pending:
            raise ServiceError(429, "Too many pending challenges; wait for one to expire")
        words = tuple(secrets.SystemRandom().sample(WORDS, 4))
        phrase = "براہ کرم یہ الفاظ کہیں: " + "، ".join(words) + "۔"
        identifier = secrets.token_urlsafe(24)
        self.challenges[identifier] = Challenge(voice_id, self.settings.model_version, revision, phrase, words,
                                               self.clock() + self.settings.liveness_challenge_seconds)
        return {"challenge_id": identifier, "voice_id": voice_id, "phrase": phrase,
                "expires_in": self.settings.liveness_challenge_seconds}

    def consume(self, identifier):
        challenge = self.challenges.pop(identifier, None)
        if challenge is None or challenge.expires <= self.clock():
            raise ServiceError(410, "Challenge expired or already used; request another")
        return challenge

    @staticmethod
    def similarity(left, right):
        left, right = np.asarray(left), np.asarray(right)
        if left.shape != right.shape or not np.isfinite(right).all():
            return -1.0
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        return float(np.clip(np.dot(left, right) / denominator, -1, 1)) if denominator else -1.0

    def _verify(self, challenge, raw, reference):
        samples, sr = decode_wav(raw, self.settings.liveness_max_seconds, self.settings.liveness_min_seconds)
        with self.lock:
            if challenge.expires <= self.clock():
                raise ServiceError(410, "Challenge expired while waiting; request another")
            try:
                transcript = canonical(self.engine.transcript(samples, sr))
                embedding = self.engine.embedding(samples, sr)
            except Exception:
                raise ServiceError(503, "Liveness models unavailable; install local Whisper and ECAPA weights") from None
        text_score = SequenceMatcher(None, canonical(challenge.phrase), transcript, autojunk=False).ratio()
        # The random words must appear in order; common prompt words alone cannot pass.
        position = 0
        for word in challenge.words:
            found = transcript.find(canonical(word), position)
            if found < 0:
                text_score = 0.0
                break
            position = found + len(canonical(word))
        speaker_score = self.similarity(reference, embedding)
        passed = text_score >= self.settings.liveness_transcript_threshold and speaker_score >= self.settings.liveness_speaker_threshold
        return passed, text_score, speaker_score

    async def verify_audio(self, challenge, raw, reference):
        return await anyio.to_thread.run_sync(self._verify, challenge, raw, reference)

    def grant(self, challenge):
        if challenge.expires <= self.clock() or challenge.model_version != self.settings.model_version:
            raise ServiceError(410, "Challenge expired during verification; request another")
        _, revision = self.reference(challenge.voice_id)
        if revision != challenge.reference_revision:
            raise ServiceError(409, "Voice verification reference changed; request another challenge")
        self.prune()
        if len(self.sessions) >= self.settings.liveness_max_pending:
            oldest = min(self.sessions, key=lambda key: self.sessions[key]["expires"])
            del self.sessions[oldest]
        token = secrets.token_urlsafe(32)
        self.sessions[hashlib.sha256(token.encode()).hexdigest()] = {
            "voice_id": challenge.voice_id, "model_version": challenge.model_version, "revision": revision,
            "expires": self.clock() + self.settings.liveness_session_seconds}
        return {"session_token": token, "voice_id": challenge.voice_id, "expires_in": self.settings.liveness_session_seconds}

    def authorize(self, voice_id, token):
        if self.settings.workflow_mode != "research" or self.settings.security_mode != "strict" or voice_id == "aria_builtin":
            return
        self.prune()
        session = self.sessions.get(hashlib.sha256((token or "").encode()).hexdigest())
        if not session or session["voice_id"] != voice_id or session["model_version"] != self.settings.model_version:
            raise ServiceError(403, "Verify this voice with a fresh liveness challenge before speaking")
        _, revision = self.reference(voice_id)
        if session["revision"] != revision:
            raise ServiceError(403, "Voice reference changed; verify again")

    def revoke(self, voice_id=None):
        self.challenges = {key: value for key, value in self.challenges.items() if voice_id and value.voice_id != voice_id}
        self.sessions = {key: value for key, value in self.sessions.items() if voice_id and value["voice_id"] != voice_id}
