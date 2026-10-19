"""Exercise the real tensor adapter independently of large downloaded weights."""
from contextlib import contextmanager

import numpy as np
import pytest

from app.config import Settings
from app.services.watermark import AudioSealEngine


def test_adapter_uses_16khz_and_eager_inference_at_output_sample_rate(tmp_path, monkeypatch):
    torch = pytest.importorskip('torch')
    audioseal = pytest.importorskip('audioseal')
    from audioseal.libs.moshi.utils import compile as compilation
    active = []
    calls = []

    @contextmanager
    def eager():
        active.append(True)
        try:
            yield
        finally:
            active.pop()

    class Network:
        def to(self, device):
            assert device == 'cpu'
            return self
        def eval(self):
            return self
        def get_watermark(self, signal, message):
            assert active and signal.shape == (1, 1, 16000)
            assert message.shape == (1, 16)
            return torch.full_like(signal, 0.001)
        def detect_watermark(self, signal, **kwargs):
            assert active and signal.shape == (1, 1, 16000)
            assert 'sample_rate' not in kwargs
            return torch.tensor(0.99), torch.tensor([[int(c) for c in settings.watermark_message_bits]])

    def loader(path, nbits):
        calls.append(nbits)
        return Network()

    monkeypatch.setattr(compilation, 'no_compile', eager)
    monkeypatch.setattr(audioseal.AudioSeal, 'load_generator', loader)
    monkeypatch.setattr(audioseal.AudioSeal, 'load_detector', loader)
    path = tmp_path / 'placeholder.pth'
    path.write_bytes(b'not loaded by fake loader')
    settings = Settings(_env_file=None, watermark_generator_path=path, watermark_detector_path=path)
    engine = AudioSealEngine(settings)
    original = np.full(24000, 0.2, dtype=np.float32)
    marked = engine.embed(original, 24000, settings.watermark_message_bits)
    score, bits = engine.detect(marked, 24000)
    assert calls == [16, 16]
    assert marked.shape == original.shape and np.isfinite(marked).all()
    assert np.mean(marked - original) == pytest.approx(0.001, abs=1e-5)
    assert score > 0.9 and bits == settings.watermark_message_bits
