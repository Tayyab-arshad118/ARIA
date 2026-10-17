"""CPU AudioSeal, applied to outbound WAVs after caching and all audio processing."""
import logging
import math
import threading
import time

import anyio
import numpy as np

from .audio_utils import encode_wav
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
        torch.set_num_threads(settings.safety_cpu_threads)
        self.torch = torch
        self.generator = AudioSeal.load_generator(str(settings.watermark_generator_path)).to("cpu").eval()
        self.detector = AudioSeal.load_detector(str(settings.watermark_detector_path)).to("cpu").eval()

    def embed(self, samples, sr, bits):
        torch = self.torch
        tensor = torch.from_numpy(np.ascontiguousarray(samples)).reshape(1, 1, -1)
        message = torch.tensor([[int(bit) for bit in bits]], dtype=torch.int64)
        with torch.no_grad():
            mark = self.generator.get_watermark(tensor, sample_rate=sr, message=message)
            return (tensor + mark).reshape(-1).cpu().numpy()

    def detect(self, samples, sr):
        tensor = self.torch.from_numpy(np.ascontiguousarray(samples)).reshape(1, 1, -1)
        with self.torch.no_grad():
            score, message = self.detector.detect_watermark(tensor, sample_rate=sr,
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
                return raw, "unavailable"

    async def apply(self, raw):
        if not self.settings.watermark_enabled:
            return raw, "disabled"
        return await anyio.to_thread.run_sync(self._apply, raw)

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
        if not self.settings.watermark_enabled:
            raise ServiceError(409, "Watermarking is disabled")
        return await anyio.to_thread.run_sync(self._detect, raw)
