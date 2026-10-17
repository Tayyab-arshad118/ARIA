import io

import numpy as np
import soundfile as sf

from .errors import ServiceError


def decode_wav(raw, max_seconds, min_seconds=0.01):
    try:
        with sf.SoundFile(io.BytesIO(raw)) as source:
            if (source.format not in {"WAV", "WAVEX"} or not 1 <= source.channels <= 2
                    or not 8000 <= source.samplerate <= 96000
                    or not min_seconds <= source.frames / source.samplerate <= max_seconds):
                raise ValueError()
            audio = source.read(dtype="float32", always_2d=True).mean(axis=1)
            sr = source.samplerate
        if not np.isfinite(audio).all():
            raise ValueError()
        return audio, sr
    except (ValueError, RuntimeError):
        raise ServiceError(422, "Use a valid WAV within the configured duration and sample-rate limits") from None
