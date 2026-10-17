"""Scan long recordings using bounded decoded buffers; retain one conditioning window."""
import io

import numpy as np
import soundfile as sf

from .errors import ServiceError


def blocks(raw, settings):
    if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
        with sf.SoundFile(io.BytesIO(raw)) as source:
            sr = source.samplerate
            if not settings.min_reference_sr <= sr <= settings.max_reference_sr or not 1 <= source.channels <= 2:
                raise ValueError("Unsupported rate or channels")
            if source.frames / sr > settings.max_source_seconds:
                raise ValueError("Recording exceeds MAX_SOURCE_SECONDS")
            size = max(1, int(settings.reference_scan_step_seconds * sr))
            while True:
                part = source.read(size, dtype="float32", always_2d=True)
                if not len(part):
                    break
                yield part, sr
        return
    kind = ("flac" if raw.startswith(b"fLaC") else "ogg" if raw.startswith(b"OggS") else
            "mov" if raw[4:8] == b"ftyp" else "mp3" if raw.startswith(b"ID3") else None)
    if kind is None and len(raw) > 1 and raw[0] == 255 and raw[1] & 0xE0 == 0xE0:
        kind = "aac" if raw[1] & 0xF6 == 0xF0 else "mp3"
    if kind is None:
        raise ValueError("Unsupported format")
    try:
        import av
    except ImportError:
        raise ServiceError(503, "Audio conversion is unavailable; install the updated backend requirements") from None
    av.logging.set_level(av.logging.PANIC)
    try:
        with av.open(io.BytesIO(raw), format=kind, options={"protocol_whitelist": "pipe", "enable_drefs": "0"}) as container:
            if not container.streams.audio:
                raise ValueError("No audio track")
            stream = container.streams.audio[0]
            stream.codec_context.thread_count = 1
            converter = None
            for frame in container.decode(stream):
                if not 1 <= len(frame.layout.channels) <= 2 or not settings.min_reference_sr <= frame.sample_rate <= settings.max_reference_sr:
                    raise ValueError("Unsupported rate or channels")
                if converter is None:
                    converter = av.AudioResampler(format="fltp", layout=frame.layout.name, rate=frame.sample_rate)
                for part in converter.resample(frame):
                    yield part.to_ndarray().T.copy(), part.sample_rate
    except av.FFmpegError:
        raise ValueError("Audio cannot be decoded") from None


def prepare_long_reference(raw, settings):
    from .audio_utils import encode_wav, resample
    if len(raw) > settings.max_upload_bytes:
        raise ServiceError(413, "Recording exceeds MAX_UPLOAD_BYTES")
    pending, pending_count, total, sr, channels = [], 0, 0, 0, 0
    window = best = None
    best_score = -1.0

    def consider(part):
        nonlocal window, best, best_score
        limit = max(1, int(settings.max_reference_seconds * sr))
        window = part[-limit:] if window is None else np.concatenate([window, part])[-limit:]
        if len(window) < settings.min_reference_seconds * sr:
            return
        clipped = float(np.mean(np.abs(window) >= 0.999))
        if clipped > settings.max_clipping_ratio:
            return
        mono = window.mean(axis=1)
        frame = max(1, int(sr * 0.02))
        padded = np.pad(mono, (0, (-len(mono)) % frame))
        rms = np.sqrt(np.mean(padded.reshape(-1, frame) ** 2, axis=1))
        active = rms >= settings.silence_threshold
        if 1 - float(active.mean()) > settings.max_silence_ratio:
            return
        # More usable voiced duration wins; do not prefer loud/clipped recordings.
        score = float(active.sum()) * frame / sr - clipped
        if score > best_score:
            best, best_score = mono.copy(), score

    try:
        for part, rate in blocks(raw, settings):
            if not sr:
                sr, channels = rate, part.shape[1]
            if rate != sr or part.shape[1] != channels or not np.isfinite(part).all():
                raise ValueError("Invalid or changing audio layout")
            total += len(part)
            if total > int(settings.max_source_seconds * sr):
                raise ValueError("Recording exceeds duration limit")
            pending.append(part)
            pending_count += len(part)
            if pending_count >= settings.reference_scan_step_seconds * sr:
                consider(np.concatenate(pending))
                pending, pending_count = [], 0
        if pending:
            consider(np.concatenate(pending))
    except (ValueError, RuntimeError):
        raise ServiceError(422, "Use valid mono/stereo audio within MAX_SOURCE_SECONDS and sample-rate limits") from None
    if best is None:
        raise ServiceError(422, "No suitable reference section found; use clear single-speaker audio with less silence or clipping")
    return encode_wav(resample(best, sr, settings.reference_sample_rate), settings.reference_sample_rate)
