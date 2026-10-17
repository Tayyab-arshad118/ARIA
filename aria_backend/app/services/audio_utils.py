from math import gcd
import io

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

from .errors import ServiceError


def encode_wav(samples, sr):
    output = io.BytesIO()
    sf.write(output, np.clip(samples, -1, 1), sr, format="WAV", subtype="PCM_16")
    return output.getvalue()


def resample(samples, source, target):
    if source == target:
        return samples
    divisor = gcd(source, target)
    return resample_poly(samples, target // divisor, source // divisor).astype(np.float32)


def prepare_reference(raw, settings):
    from .reference_audio import prepare_long_reference
    return prepare_long_reference(raw, settings)


def stitch_audio(chunks, settings):
    pieces, total = [], 0
    for raw, reported_sr in chunks:
        try:
            with sf.SoundFile(io.BytesIO(raw)) as file:
                if file.format not in {"WAV", "WAVEX"} or file.channels != 1 or file.samplerate != reported_sr:
                    raise ValueError()
                if not 0 < file.frames / file.samplerate <= settings.max_generated_seconds:
                    raise ValueError()
                samples = file.read(dtype="float32")
                sr = file.samplerate
            if not np.isfinite(samples).all():
                raise ValueError()
        except (ValueError, RuntimeError):
            raise ServiceError(502, "Colab returned an invalid WAV") from None
        samples = resample(samples, sr, settings.output_sample_rate)
        if pieces:
            pieces.append(np.zeros(int(settings.output_sample_rate * settings.silence_ms / 1000), np.float32))
        pieces.append(samples)
        total += len(samples) + (len(pieces) > 1) * int(settings.output_sample_rate * settings.silence_ms / 1000)
        if total > settings.output_sample_rate * settings.max_generated_seconds:
            raise ServiceError(422, "Generated audio is too long; use less text")
    if not pieces:
        raise ServiceError(422, "No speakable text")
    audio = np.concatenate(pieces)
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(audio)))
    if rms > 0 and peak > 0:
        audio *= min(10 ** (settings.target_dbfs / 20) / rms, 0.98 / peak)
    return encode_wav(audio, settings.output_sample_rate)
