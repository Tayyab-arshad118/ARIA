import asyncio
import base64
import io
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from urllib.parse import unquote

from cryptography.fernet import Fernet
import httpx
import numpy as np
import pytest
import soundfile as sf
from sqlalchemy import select
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Voice, AudioCache, TextCache
from app.main import create_app
from app.services.audio_utils import encode_wav
from app.services.errors import ServiceError
from app.services.gpu_client import GPUClient, UNREACHABLE


def npy(shape):
    buffer = io.BytesIO()
    np.save(buffer, np.ones(shape, np.float32), allow_pickle=False)
    return base64.b64encode(buffer.getvalue()).decode()


LATENTS = {"gpt_cond_latent": npy((1, 32, 8)), "speaker_embedding": npy((1, 4, 1))}


def reference(seconds=6, silent=False, clipped=False):
    samples = np.sin(np.arange(int(seconds * 44100)) * 0.1).astype(np.float32) * 0.2
    if silent:
        samples[:] = 0
    if clipped:
        samples[:] = 1
    return encode_wav(samples, 44100)


class FakeGPU:
    def __init__(self):
        self.url, self.key = "https://initial.trycloudflare.com", "dummy-key"
        self.calls, self.active, self.peak = [], 0, 0
        self.semaphore = asyncio.Semaphore(2)
        self.offline = False

    def configure(self, url, key=None):
        self.url = url
        if key is not None:
            self.key = key

    async def close(self):
        pass

    async def health(self):
        if self.offline:
            raise ServiceError(503, UNREACHABLE)
        return {"ok": True, "gpu": "fake", "lang": "ar"}

    async def latents(self, audio):
        data, sr = sf.read(io.BytesIO(audio))
        assert sr == 22050 and data.ndim == 1
        return dict(LATENTS)

    async def synthesize(self, text, latents, speed, language=None, temperature=None):
        async with self.semaphore:
            self.active += 1
            self.peak = max(self.active, self.peak)
            try:
                await asyncio.sleep(0.01)
                if self.offline:
                    raise ServiceError(503, UNREACHABLE)
                self.calls.append((text, speed))
                return encode_wav(np.full(2400, 0.1 if "پانی" in text else 0.2), 24000), 24000
            finally:
                self.active -= 1


@pytest.fixture
def backend(tmp_path):
    settings = Settings(_env_file=None, workflow_mode="research", watermark_policy="research_unprotected", data_dir=tmp_path, fernet_key=Fernet.generate_key().decode(), phrase_prewarm_enabled=False)
    gpu = FakeGPU()
    app = create_app(settings, gpu=gpu)
    with TestClient(app) as client:
        yield client, app, gpu


def enroll(client):
    response = client.post("/api/voices", files={"file": ("voice.wav", reference(), "audio/wav")}, data={"name": "My voice"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_api_roundtrip_headers_cache_and_delete(backend):
    client, app, gpu = backend
    assert client.get("/api/health").json()["colab"]["reachable"]
    preview = client.post("/api/transliterate", json={"text": "mujhe pani chahiye"}).json()
    assert preview["method_used"] == "dictionary"
    assert client.post("/api/tts", json={"text": "hello"}).status_code == 404
    voice_id = enroll(client)
    assert next(v for v in client.get("/api/voices").json() if v["id"] == voice_id)["is_default"]
    response = client.post("/api/tts", json={"text": "mujhe pani chahiye"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "audio/wav"
    assert unquote(response.headers["x-urdu-text"]) == "مجھے پانی چاہیے"
    assert float(response.headers["x-latency-ms"]) >= 0
    samples, sr = sf.read(io.BytesIO(response.content))
    assert sr == 24000 and len(samples) == 2400
    assert client.post("/api/tts", json={"text": "mujhe pani chahiye"}).content == response.content
    assert len(gpu.calls) == 1
    assert client.delete(f"/api/voices/{voice_id}").status_code == 204
    assert [v["id"] for v in client.get("/api/voices").json()] == ["aria_builtin"]
    with app.state.db.session() as session:
        assert session.scalar(select(AudioCache)) is None


def test_encrypted_voice_roundtrip_and_delete_all(backend):
    client, app, gpu = backend
    voice_id = enroll(client)
    with app.state.db.session() as session:
        voice = session.get(Voice, voice_id)
        assert voice.raw_audio is None
        assert LATENTS["gpt_cond_latent"].encode() not in voice.latents
        assert json.loads(app.state.cipher.decrypt(voice.latents)) == LATENTS
    client.post("/api/tts", json={"text": "mujhe pani chahiye"})
    assert client.delete("/api/voices/all").status_code == 200
    with app.state.db.session() as session:
        for table in (Voice, AudioCache, TextCache):
            assert session.scalar(select(table)) is None


def test_chunk_concurrency_order_silence_and_speed_cache(backend):
    client, app, gpu = backend
    enroll(client)
    response = client.post("/api/tts", json={"text": "پانی۔ مدد۔ شکریہ۔", "speed": 1.2})
    assert response.status_code == 200
    audio, sr = sf.read(io.BytesIO(response.content))
    assert len(audio) == 3 * 2400 + 2 * 3600
    assert np.all(audio[2400:6000] == 0)
    assert audio[0] < audio[6000]
    assert gpu.peak == 2
    assert all(speed == 1.2 for _, speed in gpu.calls)
    client.post("/api/tts", json={"text": "پانی۔ مدد۔ شکریہ۔", "speed": 1.1})
    assert len(gpu.calls) == 6


def test_model_swap_flags_and_rejects_old_voices(backend):
    client, app, gpu = backend
    enroll(client)
    app.state.settings.model_version = "new-model"
    assert any(v["needs_reenrollment"] for v in client.get("/api/voices").json() if v["id"] != "aria_builtin")
    assert client.post("/api/tts", json={"text": "pani"}).status_code == 409
    new_id = enroll(client)
    assert next(v for v in client.get("/api/voices").json() if v["is_default"])["id"] == new_id
    assert client.post("/api/tts", json={"text": "pani"}).status_code == 200


@pytest.mark.parametrize("kind", ["silent", "clipped", "short", "invalid"])
def test_voice_validation(backend, kind):
    client, _, _ = backend
    raw = {"silent": lambda: reference(silent=True), "clipped": lambda: reference(clipped=True),
           "short": lambda: reference(seconds=1), "invalid": lambda: b"not WAV"}[kind]()
    response = client.post("/api/voices", files={"file": ("ref.wav", raw)}, data={"name": "test"})
    assert response.status_code == 422


def test_offline_health_and_tts_error(backend):
    client, app, gpu = backend
    enroll(client)
    gpu.offline = True
    assert client.get("/api/health").json()["colab"]["reachable"] is False
    result = client.post("/api/tts", json={"text": "pani"})
    assert result.status_code == 503 and result.json()["detail"] == UNREACHABLE


def test_optional_auth_and_sanitized_validation(tmp_path):
    app = create_app(Settings(_env_file=None, workflow_mode="research", watermark_policy="research_unprotected", data_dir=tmp_path, aria_key="local-secret"), gpu=FakeGPU())
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 401
        assert client.delete("/api/voices/all").status_code == 401
        assert client.get("/api/health", headers={"Authorization": "Bearer local-secret"}).status_code == 200
        response = client.post("/api/tts", json={"text": "private sentence", "speed": "secret"},
                               headers={"Authorization": "Bearer local-secret"})
        assert response.status_code == 422 and "private" not in response.text and "secret" not in response.text


def test_runtime_url_key_persist_encrypted_and_no_restart(tmp_path):
    settings = Settings(_env_file=None, workflow_mode="research", watermark_policy="research_unprotected", data_dir=tmp_path)
    app = create_app(settings, gpu=FakeGPU())
    with TestClient(app) as client:
        response = client.post("/api/admin/colab-url", json={"colab_url": "https://new.trycloudflare.com/",
                                                           "colab_api_key": "new-secret"})
        assert response.status_code == 200 and "new-secret" not in response.text
        assert app.state.gpu.url == "https://new.trycloudflare.com"
        assert app.state.gpu.key == "new-secret"
        assert client.post("/api/admin/colab-url", json={"colab_url": "http://evil.test/path?key=x"}).status_code == 422
    assert b"new-secret" not in (tmp_path / "aria.sqlite").read_bytes()
    with TestClient(create_app(settings, gpu=FakeGPU())) as second:
        assert second.app.state.gpu.url == "https://new.trycloudflare.com"
        assert second.app.state.gpu.key == "new-secret"


def test_keep_raw_audio_is_encrypted(tmp_path):
    app = create_app(Settings(_env_file=None, workflow_mode="research", watermark_policy="research_unprotected", data_dir=tmp_path, keep_raw_audio=True), gpu=FakeGPU())
    with TestClient(app) as client:
        voice_id = enroll(client)
        with app.state.db.session() as session:
            voice = session.get(Voice, voice_id)
            assert not voice.raw_audio.startswith(b"RIFF")
            assert app.state.cipher.decrypt(voice.raw_audio) == reference()


def test_missing_key_does_not_replace_existing_key(tmp_path):
    settings = Settings(_env_file=None, workflow_mode="research", watermark_policy="research_unprotected", data_dir=tmp_path)
    with TestClient(create_app(settings, gpu=FakeGPU())) as client:
        enroll(client)
    (tmp_path / "voices" / ".fernet.key").unlink()
    with pytest.raises(RuntimeError, match="Encryption key missing"):
        with TestClient(create_app(settings, gpu=FakeGPU())):
            pass


def test_gpu_client_retries_and_contract(tmp_path):
    calls = []
    async def handler(request):
        calls.append(request)
        assert request.headers["x-api-key"] == "gpu-key"
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})
    async def run():
        client = GPUClient(Settings(_env_file=None, workflow_mode="research", watermark_policy="research_unprotected", data_dir=tmp_path, colab_url="https://gpu.test", colab_api_key="gpu-key",
                                    retry_backoff_seconds=0), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        assert await client.request("POST", "/synthesize", json={}) == {"ok": True}
        assert len(calls) == 2
        await client.close()
    asyncio.run(run())


@pytest.mark.parametrize("status,expected", [(401, 502), (429, 503), (502, 503), (302, 502), (404, 503)])
def test_gpu_failure_mapping(tmp_path, status, expected):
    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(status, text="sensitive upstream body"))
        client = GPUClient(Settings(_env_file=None, workflow_mode="research", watermark_policy="research_unprotected", data_dir=tmp_path, colab_url="https://gpu.test", gpu_retries=0),
                           httpx.AsyncClient(transport=transport))
        with pytest.raises(ServiceError) as error:
            await client.request("GET", "/health")
        assert error.value.status == expected and "sensitive" not in error.value.detail
        await client.close()
    asyncio.run(run())


def test_request_and_upload_size_limits(backend):
    client, app, gpu = backend
    response = client.post("/api/tts", content=b"{}", headers={"content-length": "999999999"})
    assert response.status_code == 413
    app.state.settings.max_upload_bytes = 100
    assert client.post("/api/voices", files={"file": ("ref.wav", reference())}, data={"name": "test"}).status_code == 413


def test_internal_errors_do_not_expose_exception_messages(backend, monkeypatch, caplog):
    client, app, gpu = backend
    def fail():
        raise RuntimeError("secret-user-text")
    monkeypatch.setattr(app.state.voices, "list", fail)
    response = client.get("/api/voices")
    assert response.status_code == 500
    assert "secret-user-text" not in response.text and "secret-user-text" not in caplog.text


def test_gpu_client_bounded_concurrency(tmp_path):
    active = peak = 0
    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.01)
            return httpx.Response(200, json={"wav_b64": base64.b64encode(encode_wav(np.zeros(10), 24000)).decode(), "sr": 24000})
        finally:
            active -= 1
    async def run():
        client = GPUClient(Settings(_env_file=None, workflow_mode="research", watermark_policy="research_unprotected", data_dir=tmp_path, colab_url="https://gpu.test"),
                           httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        await asyncio.gather(*(client.synthesize("پانی", LATENTS, 1.0) for _ in range(5)))
        assert peak == 2
        await client.close()
    asyncio.run(run())


def test_real_server_and_runtime_update_cli(tmp_path):
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    env = dict(os.environ)
    token = secrets.token_urlsafe(32)
    env.update(DATA_DIR=str(tmp_path), HOST="127.0.0.1", PORT=str(port), ARIA_KEY=token,
               COLAB_URL="", COLAB_API_KEY="", FERNET_KEY="", LOCAL_ONLY="true", LLM_TRANSLIT_ENABLED="false")
    root = Path(__file__).resolve().parents[1]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen([sys.executable, "-m", "app"], cwd=root, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    url = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(base_url=url, headers={"Authorization": "Bearer " + token}, trust_env=False, timeout=1) as client:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                assert process.poll() is None, "Backend exited before becoming ready"
                try:
                    health = client.get("/api/health")
                    if health.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                pytest.fail("Backend did not become ready")
            assert health.json()["colab"]["reachable"] is False
            preview = client.post("/api/transliterate", json={"text": "mujhe pani chahiye"})
            assert preview.json()["urdu"] == "مجھے پانی چاہیے"
            command = subprocess.run([sys.executable, "-m", "app.cli", "set-colab-url",
                "https://cli-test.trycloudflare.com", "--backend", url], cwd=root, env=env,
                capture_output=True, text=True, timeout=15, creationflags=flags)
            assert command.returncode == 0, command.stderr
            assert "No restart needed" in command.stdout
            assert token not in command.stdout + command.stderr
            assert client.get("/api/voices").status_code == 200
    finally:
        process.terminate()
        process.wait(timeout=10)
