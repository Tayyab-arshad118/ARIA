import asyncio
import json

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import EmotionReference, PhraseAudio, VerificationProfile
from app.main import create_app
from app.services.emotion import classify
from app.services.errors import ServiceError
from test_api import FakeGPU, reference


class Verification:
    def __init__(self):
        self.text = ""
        self.vector = np.array([1.0, 0, 0], dtype=np.float32)
        self.fail = False

    def embedding(self, audio, sr):
        if self.fail:
            raise RuntimeError("private error detail")
        return self.vector.copy()

    def transcript(self, audio, sr):
        if self.fail:
            raise RuntimeError("private transcript detail")
        return self.text


class Watermark:
    def __init__(self):
        self.calls = 0
        self.fail = False

    def embed(self, audio, sr, bits):
        self.calls += 1
        if self.fail:
            raise RuntimeError("private watermark error")
        return audio + np.float32(0.001)

    def detect(self, audio, sr):
        if self.fail:
            raise RuntimeError("private detector error")
        return 0.99, "0100000101010010"


class EmotionGPU(FakeGPU):
    def __init__(self):
        super().__init__()
        self.temperatures = []

    async def synthesize(self, text, latents, speed, temperature=None, language=None):
        self.temperatures.append(temperature)
        return await super().synthesize(text, latents, speed, language=language)


@pytest.fixture
def safe(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, security_mode="strict", watermark_enabled=True,
                        emotion_enabled=True, phrase_prewarm_enabled=False)
    verification, watermark, gpu = Verification(), Watermark(), EmotionGPU()
    app = create_app(settings, gpu=gpu, verification_engine=verification, watermark_engine=watermark)
    with TestClient(app) as client:
        yield client, app, verification, watermark, gpu


def enroll(client):
    response = client.post("/api/voices", files={"file": ("ref.wav", reference())}, data={"name": "Test"})
    assert response.status_code == 201, response.text
    assert response.json()["verification_ready"]
    return response.json()["id"]


def verified(client, engine, voice):
    challenge = client.post("/api/liveness/challenge", json={"voice_id": voice})
    assert challenge.status_code == 200, challenge.text
    challenge = challenge.json()
    engine.text = challenge["phrase"]
    response = client.post("/api/liveness/verify", files={"file": ("check.wav", reference())},
                           data={"challenge_id": challenge["challenge_id"]})
    assert response.status_code == 200, response.text
    return {"X-ARIA-Session": response.json()["session_token"]}, challenge


def test_strict_gates_tts_and_phrase_cache_hits(safe):
    client, app, verifier, watermark, gpu = safe
    voice = enroll(client)
    assert client.post("/api/tts", json={"text": "pani", "voice_id": voice}).status_code == 403
    assert client.post("/api/phrases/needs-1/speak", json={"voice_id": voice}).status_code == 403
    headers, challenge = verified(client, verifier, voice)
    for path, body in (("/api/tts", {"text": "pani", "voice_id": voice}),
                        ("/api/phrases/needs-1/speak", {"voice_id": voice})):
        first = client.post(path, json=body, headers=headers)
        assert first.status_code == 200
        assert first.headers["x-aria-generated"] == "true" and first.headers["x-aria-watermark"] == "embedded"
        count = len(gpu.calls)
        assert client.post(path, json=body, headers=headers).status_code == 200
        assert len(gpu.calls) == count
        assert client.post(path, json=body).status_code == 403
    assert watermark.calls == 4
    repeat = client.post("/api/liveness/verify", files={"file": ("r.wav", reference())},
                         data={"challenge_id": challenge["challenge_id"]})
    assert repeat.status_code == 410


@pytest.mark.parametrize("failure", ["text", "speaker", "unavailable", "nonce"])
def test_challenge_failures_cannot_grant_session(safe, failure):
    client, app, verifier, watermark, gpu = safe
    voice = enroll(client)
    challenge = client.post("/api/liveness/challenge", json={"voice_id": voice}).json()
    verifier.text = challenge["phrase"]
    if failure == "text":
        verifier.text = "غلط الفاظ"
    elif failure == "speaker":
        verifier.vector = np.array([0, 1.0, 0])
    elif failure == "unavailable":
        verifier.fail = True
    else:
        verifier.text = "براہ کرم یہ الفاظ کہیں"
    result = client.post("/api/liveness/verify", files={"file": ("c.wav", reference())},
                         data={"challenge_id": challenge["challenge_id"]})
    assert result.status_code == (503 if failure == "unavailable" else 403)
    assert "private" not in result.text and not app.state.liveness.sessions
    assert client.post("/api/liveness/verify", files={"file": ("c.wav", reference())},
                       data={"challenge_id": challenge["challenge_id"]}).status_code == 410


def test_expiry_voice_binding_and_revocation(safe):
    client, app, verifier, watermark, gpu = safe
    now = [100.0]
    app.state.liveness.clock = lambda: now[0]
    voice = enroll(client)
    expired = client.post("/api/liveness/challenge", json={"voice_id": voice}).json()
    now[0] += 61
    assert client.post("/api/liveness/verify", files={"file": ("c.wav", reference())},
                       data={"challenge_id": expired["challenge_id"]}).status_code == 410
    headers, _ = verified(client, verifier, voice)
    other = enroll(client)
    assert client.post("/api/tts", json={"text": "pani", "voice_id": other}, headers=headers).status_code == 403
    now[0] += app.state.settings.liveness_session_seconds + 1
    assert client.post("/api/tts", json={"text": "pani", "voice_id": voice}, headers=headers).status_code == 403
    headers, _ = verified(client, verifier, voice)
    assert client.delete(f"/api/voices/{voice}").status_code == 204
    assert not app.state.liveness.sessions


def test_token_expiring_during_synthesis_is_rejected(safe):
    client, app, verifier, watermark, gpu = safe
    now = [100.0]
    app.state.liveness.clock = lambda: now[0]
    voice = enroll(client)
    headers, _ = verified(client, verifier, voice)
    original = gpu.synthesize
    async def delayed(*args, **kwargs):
        result = await original(*args, **kwargs)
        now[0] += app.state.settings.liveness_session_seconds + 1
        return result
    gpu.synthesize = delayed
    assert client.post("/api/tts", json={"text": "pani", "voice_id": voice}, headers=headers).status_code == 403


def test_watermark_failure_degrades_and_detection_reports_unavailable(safe, caplog):
    client, app, verifier, watermark, gpu = safe
    voice = enroll(client)
    headers, _ = verified(client, verifier, voice)
    watermark.fail = True
    response = client.post("/api/tts", json={"text": "pani"}, headers=headers)
    assert response.status_code == 200 and response.headers["x-aria-watermark"] == "unavailable"
    assert response.content.startswith(b"RIFF") and response.headers["x-aria-generated"] == "true"
    assert "audioseal_unavailable" in caplog.text and "private" not in caplog.text
    result = client.post("/api/watermark/detect", files={"file": ("a.wav", reference())})
    assert result.status_code == 503 and "private" not in result.text


def test_watermark_detection_and_encrypted_verification_reference(safe):
    client, app, verifier, watermark, gpu = safe
    voice = enroll(client)
    result = client.post("/api/watermark/detect", files={"file": ("a.wav", reference())})
    assert result.status_code == 200 and result.json()["aria_payload_match"]
    with app.state.db.session() as session:
        stored = session.get(VerificationProfile, voice)
        assert json.loads(app.state.cipher.decrypt(stored.embedding)) == [1.0, 0.0, 0.0]
        assert not stored.embedding.startswith(b"[")


def test_emotion_reference_update_invalidates_cache_and_matches_speaker(safe):
    client, app, verifier, watermark, gpu = safe
    voice = enroll(client)
    headers, _ = verified(client, verifier, voice)
    spoken = {"text": "میں خوش ہوں", "voice_id": voice}
    first = client.post("/api/tts", json=spoken, headers=headers)
    assert first.status_code == 200 and first.headers["x-aria-emotion"] == "happy"
    assert gpu.calls[-1][1] == 1.05 and gpu.temperatures[-1] == 0.68
    count = len(gpu.calls)
    client.post("/api/tts", json=spoken, headers=headers)
    assert len(gpu.calls) == count
    route = f"/api/voices/{voice}/emotions/happy"
    assert client.post(route, files={"file": ("happy.wav", reference())}, headers=headers).status_code == 201
    assert client.get(f"/api/voices/{voice}/emotions").json()[0]["emotion"] == "happy"
    client.post("/api/tts", json=spoken, headers=headers)
    assert len(gpu.calls) == count + 1
    with app.state.db.session() as session:
        assert session.get(EmotionReference, (voice, "happy")).raw_audio is None
    verifier.vector = np.array([0, 1.0, 0])
    assert client.post(route, files={"file": ("happy.wav", reference())}, headers=headers).status_code == 403
    assert client.delete(route, headers=headers).status_code == 204


def test_disabled_and_basic_modes(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, phrase_prewarm_enabled=False)
    app = create_app(settings, gpu=FakeGPU(), verification_engine=Verification())
    with TestClient(app) as client:
        voice = client.post("/api/voices", files={"file": ("ref.wav", reference())}, data={"name": "Old"}).json()["id"]
        assert client.post("/api/liveness/challenge", json={"voice_id": voice}).status_code == 409
        response = client.post("/api/tts", json={"text": "pani"})
        assert response.status_code == 200 and response.headers["x-aria-watermark"] == "disabled"
        settings.security_mode = "basic"
        assert client.post("/api/liveness/challenge", json={"voice_id": voice}).status_code == 409
        assert client.post("/api/tts", json={"text": "pani"}).status_code == 200
        settings.security_mode = "strict"
        assert client.post("/api/tts", json={"text": "pani"}).status_code == 403


def test_delete_all_removes_safety_data_and_tokens(safe):
    client, app, verifier, watermark, gpu = safe
    voice = enroll(client)
    headers, _ = verified(client, verifier, voice)
    client.post(f"/api/voices/{voice}/emotions/happy", files={"file": ("ref.wav", reference())}, headers=headers)
    assert client.delete("/api/voices/all").status_code == 200
    with app.state.db.session() as session:
        assert session.scalar(select(VerificationProfile)) is None
        assert session.scalar(select(EmotionReference)) is None
    assert not app.state.liveness.challenges and not app.state.liveness.sessions


def test_challenge_expiring_during_cpu_verification_cannot_grant_token(safe):
    client, app, verifier, watermark, gpu = safe
    now = [100.0]
    app.state.liveness.clock = lambda: now[0]
    voice = enroll(client)
    challenge = client.post("/api/liveness/challenge", json={"voice_id": voice}).json()
    def slow_transcript(audio, sr):
        now[0] += 61
        return challenge["phrase"]
    verifier.transcript = slow_transcript
    result = client.post("/api/liveness/verify", files={"file": ("c.wav", reference())},
                         data={"challenge_id": challenge["challenge_id"]})
    assert result.status_code == 410 and not app.state.liveness.sessions


def test_missing_models_fail_closed_and_watermark_falls_back(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, security_mode="strict", watermark_enabled=True,
        liveness_speaker_path=tmp_path / "missing", watermark_generator_path=tmp_path / "missing.pth",
        watermark_detector_path=tmp_path / "missing2.pth", phrase_prewarm_enabled=False)
    app = create_app(settings, gpu=FakeGPU())
    with TestClient(app) as client:
        result = client.post("/api/voices", files={"file": ("ref.wav", reference())}, data={"name": "Test"})
        assert result.status_code == 503
        assert client.get("/api/voices").json() == []
        settings.security_mode = "off"
        assert client.post("/api/voices", files={"file": ("ref.wav", reference())}, data={"name": "Test"}).status_code == 201
        response = client.post("/api/tts", json={"text": "pani"})
        assert response.status_code == 200 and response.headers["x-aria-watermark"] == "unavailable"


def test_invalid_settings_do_not_echo_credentials():
    with pytest.raises(ValueError) as error:
        Settings(_env_file=None, colab_url="https://user:private-key@example.com", groq_api_key="private-groq-key")
    assert "private-key" not in str(error.value) and "private-groq-key" not in str(error.value)


@pytest.mark.parametrize("text,label", [("میں خوش ہوں", "happy"), ("میں خوش نہیں ہوں", "neutral"),
                                      ("مجھے درد ہے", "sad"), ("آرام چاہیے", "calm"), ("مجھے پانی چاہیے", "neutral")])
def test_local_lexicon(text, label):
    assert classify(text) == label
