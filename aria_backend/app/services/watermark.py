"""CPU AudioSeal, validated after final processing and before protected caching."""
import logging
import math
import threading
import time
import hashlib
import json

import anyio
import numpy as np

from .audio_utils import encode_wav, resample
from .errors import ServiceError
from .safety_audio import decode_wav

log = logging.getLogger("aria.backend")


class AudioSealEngine:
    def __init__(self, settings):
        self.settings = settings
        # Require local files BEFORE calling a loader that also accepts remote model cards.
        if not settings.watermark_generator_path.is_file() or not settings.watermark_detector_path.is_file():
            raise RuntimeError("Local AudioSeal weights are missing")
        import torch
        from audioseal import AudioSeal
        from audioseal.libs.moshi.utils.compile import no_compile
        torch.set_num_threads(settings.safety_cpu_threads)
        self.torch = torch
        # Eager inference works on CPU installations without a C++ build toolchain.
        self.no_compile = no_compile
        nbits = len(settings.watermark_message_bits)
        self.generator = AudioSeal.load_generator(str(settings.watermark_generator_path), nbits=nbits).to("cpu").eval()
        self.detector = AudioSeal.load_detector(str(settings.watermark_detector_path), nbits=nbits).to("cpu").eval()

    def embed(self, samples, sr, bits):
        torch = self.torch
        # AudioSeal 0.2 does not resample internally; its base models use 16 kHz.
        tensor = torch.from_numpy(np.ascontiguousarray(resample(samples, sr, 16000))).reshape(1, 1, -1)
        message = torch.tensor([[int(bit) for bit in bits]], dtype=torch.int64)
        with torch.no_grad(), self.no_compile():
            mark = self.generator.get_watermark(tensor, message=message)
            delta = resample(mark.reshape(-1).cpu().numpy(), 16000, sr)
            delta = np.pad(delta, (0, max(0, len(samples) - len(delta))))[:len(samples)]
            return samples + delta

    def detect(self, samples, sr):
        tensor = self.torch.from_numpy(np.ascontiguousarray(resample(samples, sr, 16000))).reshape(1, 1, -1)
        with self.torch.no_grad(), self.no_compile():
            score, message = self.detector.detect_watermark(tensor,
                message_threshold=self.settings.watermark_bit_threshold,
                detection_threshold=self.settings.watermark_frame_threshold)
        score = float(score.item()) if hasattr(score, "item") else float(score)
        bits = "".join(str(int(bit)) for bit in message.reshape(-1).cpu().tolist())
        return score, bits


class Watermarker:
    def __init__(self, settings, engine=None):
        self.settings, self.engine = settings, engine
        self.lock = threading.Lock()
        self.retry_after = 0.0
        self.available = engine is not None
        self._weight_hashes = {}

    def fingerprint(self):
        weights = []
        for path in (self.settings.watermark_generator_path, self.settings.watermark_detector_path):
            try:
                stat = path.stat()
                key = (str(path), stat.st_size, stat.st_mtime_ns)
                if key not in self._weight_hashes:
                    with path.open("rb") as source:
                        digest = hashlib.file_digest(source, "sha256").hexdigest()
                    self._weight_hashes = {k: v for k, v in self._weight_hashes.items() if k[0] != str(path)}
                    self._weight_hashes[key] = digest
                weights.append(self._weight_hashes[key])
            except OSError:
                weights.append("missing")
        return [self.settings.watermark_policy, self.settings.watermark_enabled, self.settings.watermark_version,
            self.settings.watermark_message_bits, self.settings.watermark_threshold,
            self.settings.watermark_bit_threshold, self.settings.watermark_frame_threshold, weights, "final-pcm-v2-16k"]

    def load(self):
        if not self.available and time.monotonic() < self.retry_after:
            raise RuntimeError("Watermarker cooling down")
        if self.engine is None:
            self.engine = AudioSealEngine(self.settings)
        self.available = True
        return self.engine

    def failed(self):
        if time.monotonic() >= self.retry_after:
            log.warning('{"event":"audioseal_unavailable","watermarked":false}')
            self.retry_after = time.monotonic() + self.settings.watermark_retry_seconds
        self.available = False

    def _apply(self, raw):
        with self.lock:
            try:
                engine = self.load()
                audio, sr = decode_wav(raw, self.settings.max_generated_seconds)
                size = self.settings.watermark_chunk_seconds * sr
                chunks = []
                for offset in range(0, len(audio), size):
                    block = audio[offset:offset + size]
                    padded = np.pad(block, (0, max(0, sr - len(block))))
                    output = np.asarray(engine.embed(padded, sr, self.settings.watermark_message_bits), dtype=np.float32)
                    if output.shape != padded.shape or not np.isfinite(output).all():
                        raise ValueError("Invalid watermark output")
                    chunks.append(output[:len(block)])
                return encode_wav(np.concatenate(chunks), sr), "embedded"
            except Exception:
                self.failed()
                raise ServiceError(503, "Protected speech unavailable: AudioSeal embedding failed; check local models and retry") from None

    async def apply(self, raw):
        if self.settings.watermark_policy == "research_unprotected" and not self.settings.watermark_enabled:
            return raw, "research_unprotected"
        return await anyio.to_thread.run_sync(self._apply, raw)

    def _validate(self, raw):
        with self.lock:
            try:
                engine = self.load()
                samples, sr = decode_wav(raw, self.settings.max_generated_seconds)
                size = self.settings.watermark_chunk_seconds * sr
                for offset in range(0, len(samples), size):
                    block = samples[offset:offset + size]
                    score, bits = engine.detect(np.pad(block, (0, max(0, sr - len(block)))), sr)
                    if not math.isfinite(score) or score < self.settings.watermark_threshold or score > 1 or bits != self.settings.watermark_message_bits:
                        raise ValueError("Watermark validation failed")
                return True
            except Exception:
                self.failed()
                raise ServiceError(503, "Protected speech withheld: watermark validation failed; retry or check AudioSeal") from None

    async def finalize(self, raw, cached=False):
        if self.settings.watermark_policy == "research_unprotected" and not self.settings.watermark_enabled:
            return raw, "research_unprotected"
        if not cached:
            raw, _ = await self.apply(raw)
        # Validate the actual encoded bytes returned to the client, including every chunk.
        await anyio.to_thread.run_sync(self._validate, raw)
        return raw, "verified"

    def _detect(self, raw):
        audio, sr = decode_wav(raw, self.settings.watermark_detect_max_seconds)
        with self.lock:
            try:
                engine = self.load()
                # Chunk detection bounds CPU memory; aggregate scores by original duration.
                size, total, best_bits, best_score = self.settings.watermark_chunk_seconds * sr, 0.0, None, -1.0
                for offset in range(0, len(audio), size):
                    block = audio[offset:offset + size]
                    score, bits = engine.detect(np.pad(block, (0, max(0, sr - len(block)))), sr)
                    if not math.isfinite(score) or not 0 <= score <= 1:
                        raise ValueError("Invalid detector score")
                    total += score * len(block)
                    if score > best_score:
                        best_score, best_bits = score, bits
                score = total / len(audio)
                detected = score >= self.settings.watermark_threshold
                return {"detected": detected, "score": score, "message_bits": best_bits if detected else None,
                        "aria_payload_match": bool(detected and best_bits == self.settings.watermark_message_bits)}
            except Exception:
                self.failed()
                raise ServiceError(503, "AudioSeal is unavailable; install its dependencies and local model weights") from None

    async def detect(self, raw):
        if self.settings.watermark_policy != "required" and not self.settings.watermark_enabled:
            raise ServiceError(409, "Watermarking is disabled")
        return await anyio.to_thread.run_sync(self._detect, raw)
