import io

import av
import numpy as np
import pytest
import soundfile as sf

from app.config import Settings
from app.services.audio_utils import prepare_reference
from app.services.errors import ServiceError
from test_api import backend, reference


def compressed(kind, seconds=7):
    output = io.BytesIO()
    with av.open(output, mode="w", format="mp3" if kind == "mp3" else "mp4") as container:
        stream = container.add_stream("libmp3lame" if kind == "mp3" else "aac", rate=44100)
        stream.layout = "mono"
        samples = (np.sin(np.arange(int(seconds * 44100)) * 0.1) * 0.2).astype(np.float32)
        frame = av.AudioFrame.from_ndarray(samples[None, :], format="fltp", layout="mono")
        frame.sample_rate = 44100
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return output.getvalue()


@pytest.mark.parametrize("kind", ["mp3", "m4a"])
def test_conversion_to_mono_pcm_wav(kind, tmp_path):
    raw = prepare_reference(compressed(kind), Settings(_env_file=None, workflow_mode="research", watermark_policy="research_unprotected", data_dir=tmp_path))
    with sf.SoundFile(io.BytesIO(raw)) as file:
        assert file.format == "WAV" and file.subtype == "PCM_16"
        assert file.samplerate == 22050 and file.channels == 1
        assert 6.9 < file.frames / file.samplerate < 7.2


@pytest.mark.parametrize("kind", ["mp3", "m4a"])
def test_upload_converts_before_gpu_enrollment(backend, kind):
    client, app, gpu = backend
    response = client.post("/api/voices", files={"file": ("reference." + kind, compressed(kind), "application/octet-stream")},
                           data={"name": "Converted recording"})
    assert response.status_code == 201, response.text
    # The existing FakeGPU.latents asserts that it receives 22.05 kHz mono WAV.


@pytest.mark.parametrize("raw", [b"#EXTM3U\nhttps://example.com/audio.mp3", b"file:///etc/passwd", b"not audio"])
def test_reject_non_audio_and_playlists(raw, tmp_path):
    with pytest.raises(ServiceError) as error:
        prepare_reference(raw, Settings(_env_file=None, workflow_mode="research", watermark_policy="research_unprotected", data_dir=tmp_path))
    assert error.value.status == 422


def test_compressed_duration_limit(tmp_path):
    with pytest.raises(ServiceError):
        prepare_reference(compressed("mp3", 8), Settings(_env_file=None, workflow_mode="research", watermark_policy="research_unprotected", data_dir=tmp_path, max_reference_seconds=7, max_source_seconds=7))


def test_long_upload_skips_silent_intro_and_sends_bounded_reference(backend):
    client, app, gpu = backend
    samples = np.zeros(90 * 44100, np.float32)
    samples[40 * 44100:] = np.sin(np.arange(50 * 44100) * 0.1) * 0.2
    source = io.BytesIO()
    sf.write(source, samples, 44100, format="WAV", subtype="PCM_16")
    raw = source.getvalue()
    assert len(raw) > 6 * 1024 * 1024
    received = []
    original = gpu.latents
    async def latents(audio):
        received.append(audio)
        return await original(audio)
    gpu.latents = latents
    response = client.post("/api/voices", files={"file": ("long.wav", raw, "audio/wav")}, data={"name": "Long"})
    assert response.status_code == 201, response.text
    result, sr = sf.read(io.BytesIO(received[0]))
    assert sr == 22050 and len(result) == 30 * sr
    assert np.sqrt(np.mean(result ** 2)) > 0.1
    assert len(received[0]) < 2 * 1024 * 1024


def test_long_compressed_recording_and_source_limits(tmp_path):
    settings = Settings(_env_file=None, workflow_mode="research", watermark_policy="research_unprotected", data_dir=tmp_path)
    result, sr = sf.read(io.BytesIO(prepare_reference(compressed("mp3", 65), settings)))
    assert len(result) == 30 * sr
    settings.max_source_seconds = 60
    with pytest.raises(ServiceError) as error:
        prepare_reference(reference(61), settings)
    assert error.value.status == 422
    settings.max_upload_bytes = 1024
    with pytest.raises(ServiceError) as error:
        prepare_reference(reference(), settings)
    assert error.value.status == 413


@pytest.mark.parametrize("kind", ["silent", "clipped"])
def test_long_unusable_recording_is_rejected(kind, tmp_path):
    with pytest.raises(ServiceError) as error:
        prepare_reference(reference(65, **{kind: True}), Settings(_env_file=None, workflow_mode="research", watermark_policy="research_unprotected", data_dir=tmp_path))
    assert error.value.status == 422
