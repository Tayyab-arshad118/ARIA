import hashlib
import json
import asyncio
import base64

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import AccessActor, AudioCache, PhraseAudio, Voice, VoiceConsent, EmotionReference, RuntimeSetting
from app.main import create_app
from app.services.errors import ServiceError
from test_api import FakeGPU, LATENTS, reference

FP = "a" * 64


class Model(FakeGPU):
    model_fingerprint = FP
    async def health(self):
        if self.offline:
            raise ServiceError(503, "offline")
        return {"ok": True, "lang": "ar", "languages": ["ar", "en", "hi"], "model_fingerprint": self.model_fingerprint}
    async def latents(self, raw):
        return {**LATENTS, "model_fingerprint": self.model_fingerprint}
    async def synthesize(self, text, latents, speed, language=None, temperature=None):
        self.last_text, self.last_language, self.last_latents = text, language, latents
        return await super().synthesize(text, latents, speed, language=language)


class Mark:
    def __init__(self):
        self.embeds = self.detects = 0
        self.fail_embed = self.fail_detect = False
    def embed(self, samples, sr, bits):
        self.embeds += 1
        if self.fail_embed:
            raise RuntimeError("test failure")
        return samples + np.float32(0.001)
    def detect(self, samples, sr):
        self.detects += 1
        return (0.0 if self.fail_detect else 0.99), "0100000101010010"


@pytest.fixture
def protected(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, aria_key="x" * 48, require_auth=True,
        phrase_prewarm_enabled=False, watermark_retry_seconds=1)
    gpu, mark = Model(), Mark()
    app = create_app(settings, gpu=gpu, watermark_engine=mark)
    with TestClient(app, headers={"Authorization": "Bearer " + "x" * 48}) as client:
        yield client, app, gpu, mark


def approval(client, raw, headers=None):
    response = client.post("/api/access/authorizations", json={"recording_sha256": hashlib.sha256(raw).hexdigest(),
        "source_type": "historical", "basis": "patient_consent", "authorization_reference": "test informed authorization"}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["authorization_id"]


def enroll_authorized(client, headers=None):
    raw = reference()
    identifier = approval(client, raw)
    response = client.post("/api/voices", data={"name": "Historical voice", "authorization_id": identifier},
        files={"file": ("history.wav", raw)}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_builtin_no_enrollment_and_delete_all_preserves_generic_voice(protected, tmp_path):
    client, app, gpu, mark = protected
    profile = client.get("/api/voices").json()[0]
    assert profile["id"] == "aria_builtin" and profile["status"] == "not_configured"
    assert client.post("/api/tts", json={"voice_id": "aria_builtin", "text": "Hello", "language": "en"}).status_code == 503
    raw = reference()
    (tmp_path / "synthetic.wav").write_bytes(raw)
    manifest = tmp_path / "voice.json"
    manifest.write_text(json.dumps({"synthetic": True, "redistribution_permitted": True,
        "license": "Test fixture only", "license_source": "Generated synthetic test signal",
        "reference": "synthetic.wav", "sha256": hashlib.sha256(raw).hexdigest()}))
    app.state.settings.builtin_voice_manifest = manifest
    response = client.post("/api/tts", json={"voice_id": "aria_builtin", "text": "Hello", "language": "en"})
    assert response.status_code == 200, response.text
    assert response.headers["x-aria-watermark"] == "verified"
    assert mark.embeds == 1 and mark.detects == 1
    assert client.delete("/api/voices/all").status_code == 200
    gpu.offline = True
    assert client.get("/api/voices").json()[0]["id"] == "aria_builtin"
    assert client.post("/api/tts", json={"voice_id": "aria_builtin", "text": "Hello", "language": "en"}).status_code == 200
    assert mark.embeds == 1 and mark.detects == 2


@pytest.mark.parametrize("failure", ["fail_embed", "fail_detect"])
def test_protection_failure_never_returns_or_caches_audio(protected, failure):
    client, app, gpu, mark = protected
    enroll_authorized(client)
    setattr(mark, failure, True)
    response = client.post("/api/tts", json={"text": "نہیں چاہیے میں طیب گھڑی کھڑکی", "input_mode": "native"})
    assert response.status_code == 503 and response.headers["content-type"] == "application/json"
    with app.state.db.session() as session:
        assert session.scalar(select(AudioCache)) is None
    response = client.post("/api/phrases/needs-1/speak", json={})
    assert response.status_code == 503
    with app.state.db.session() as session:
        assert session.scalar(select(PhraseAudio)) is None


def test_native_urdu_manual_emotion_and_protected_cache(protected):
    client, app, gpu, mark = protected
    voice = enroll_authorized(client)
    text = "نہیں چاہیے میں طیب گھڑی کھڑکی"
    for emotion in ["sad", "neutral"]:
        response = client.post("/api/tts", json={"text": text, "input_mode": "native", "emotion": emotion})
        assert response.status_code == 200, response.text
        assert gpu.last_text == text
        assert response.headers["x-aria-emotion-requested"] == emotion
        assert response.headers["x-aria-emotion"] == "neutral"  # honest missing-reference fallback
    assert mark.embeds == 2
    assert client.post("/api/tts", json={"text": text, "input_mode": "native", "emotion": "sad"}).status_code == 200
    assert mark.embeds == 2 and mark.detects == 3
    mark.fail_detect = True
    assert client.post("/api/tts", json={"text": text, "input_mode": "native", "emotion": "sad"}).status_code == 503


def test_consent_caregiver_scope_revocation_and_pin_lockout(protected):
    client, app, gpu, mark = protected
    setup = client.post("/api/access/setup", json={"pin": "123456"})
    assert setup.status_code == 201
    patient = {"X-ARIA-Account": setup.json()["account_token"]}
    client.headers.update(patient)
    voice = enroll_authorized(client)
    caregiver = client.post("/api/access/caregivers", json={"pin": "654321", "permissions": ["speak"]}).json()["actor_id"]
    login = client.post("/api/access/login", json={"actor_id": caregiver, "pin": "654321"}).json()
    helper = {"X-ARIA-Account": login["account_token"]}
    assert client.post("/api/tts", json={"text": "hello"}, headers=helper).status_code == 200
    assert client.post("/api/access/authorizations", json={"recording_sha256": "a"*64,
        "source_type": "historical", "basis": "patient_consent", "authorization_reference": "not patient consent"}, headers=helper).status_code == 403
    assert client.delete(f"/api/voices/{voice}", headers=helper).status_code == 403
    assert client.delete(f"/api/access/caregivers/{caregiver}").status_code == 204
    assert client.post("/api/tts", json={"text": "hello"}, headers=helper).status_code in {401, 403}
    assert client.post(f"/api/voices/{voice}/revoke").status_code == 204
    assert client.post("/api/tts", json={"text": "hello"}).status_code == 403
    for _ in range(5):
        assert client.post("/api/access/login", json={"pin": "000000"}).status_code == 401
    assert client.post("/api/access/login", json={"pin": "123456"}).status_code == 429
    with app.state.db.session() as session:
        assert "123456" not in session.get(AccessActor, "patient").pin_hash
        assert b"test informed authorization" not in session.get(VoiceConsent, voice).content


def test_no_spoken_baseline_needed_and_changed_checkpoint_rejected(protected):
    client, app, gpu, mark = protected
    app.state.settings.security_mode = "basic"
    async def forbidden(*args):
        pytest.fail("Assistive enrollment must not invoke speaker verification")
    app.state.liveness.enrollment_embedding = forbidden
    voice = enroll_authorized(client)
    assert client.post("/api/tts", json={"text": "hello"}).status_code == 200
    gpu.model_fingerprint = "b" * 64
    assert client.post("/api/tts", json={"text": "hello"}).status_code == 409
    with app.state.db.session() as session:
        assert session.get(Voice, voice) is not None


def test_assistive_defaults_cannot_enable_unprotected_or_strict_workflow(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    assert settings.workflow_mode == "assistive" and settings.watermark_policy == "required"
    with pytest.raises(ValueError):
        Settings(_env_file=None, security_mode="strict")
    with pytest.raises(ValueError):
        Settings(_env_file=None, watermark_policy="research_unprotected")


def test_manual_reference_beats_lexicon_and_revoke_invalidates_it(protected):
    client, app, gpu, mark = protected
    voice = enroll_authorized(client)
    raw = reference()
    grant = approval(client, raw)
    result = client.post(f"/api/voices/{voice}/emotions/sad", files={"file": ("old-style.wav", raw)}, data={"authorization_id": grant})
    assert result.status_code == 201, result.text
    response = client.post("/api/tts", json={"text": "میں خوش ہوں", "input_mode": "native", "emotion": "sad"})
    assert response.status_code == 200, response.text
    assert response.headers["x-aria-emotion"] == "sad"
    assert response.headers["x-aria-emotion-method"] == "reference_conditioning"
    assert gpu.last_latents["authorization"]["authorization_id"] == grant
    assert client.delete("/api/access/authorizations/" + grant).status_code == 204
    response = client.post("/api/tts", json={"text": "میں خوش ہوں", "input_mode": "native", "emotion": "sad"})
    assert response.status_code == 200 and response.headers["x-aria-emotion-method"] == "neutral_fallback"


def test_scoped_caregiver_can_import_only_exact_patient_approved_recording(protected):
    client, app, gpu, mark = protected
    setup = client.post("/api/access/setup", json={"pin": "123456"}).json()
    client.headers["X-ARIA-Account"] = setup["account_token"]
    caregiver = client.post("/api/access/caregivers", json={"pin": "654321", "permissions": ["enroll"]}).json()["actor_id"]
    token = client.post("/api/access/login", json={"actor_id": caregiver, "pin": "654321"}).json()["account_token"]
    raw = reference()
    grant = approval(client, raw)
    helper = {"X-ARIA-Account": token}
    wrong = client.post("/api/voices", files={"file": ("other.wav", reference(7))}, data={"name": "No", "authorization_id": grant}, headers=helper)
    assert wrong.status_code == 403
    result = client.post("/api/voices", files={"file": ("old.wav", raw)}, data={"name": "Approved", "authorization_id": grant}, headers=helper)
    assert result.status_code == 201, result.text
    voice = result.json()["id"]
    assert client.post("/api/tts", json={"text": "hello", "voice_id": voice}, headers=helper).status_code == 403
    again = client.post("/api/voices", files={"file": ("old.wav", raw)}, data={"name": "Replay", "authorization_id": grant}, headers=helper)
    assert again.status_code == 403
    metadata = app.state.access.consent(voice)
    assert metadata["enrolling_actor"] == caregiver and metadata["beneficiary"] == "patient"


def test_recovery_rotates_code_and_revokes_caregiver_sessions(protected):
    client, app, gpu, mark = protected
    setup = client.post("/api/access/setup", json={"pin": "123456"}).json()
    client.headers["X-ARIA-Account"] = setup["account_token"]
    caregiver = client.post("/api/access/caregivers", json={"pin": "654321", "permissions": ["speak"]}).json()["actor_id"]
    token = client.post("/api/access/login", json={"actor_id": caregiver, "pin": "654321"}).json()["account_token"]
    recovered = client.post("/api/access/recover", json={"pin": "123457", "recovery_code": setup["recovery_code"]})
    assert recovered.status_code == 200
    assert recovered.json()["recovery_code"] != setup["recovery_code"]
    assert client.post("/api/access/recover", json={"pin": "123458", "recovery_code": setup["recovery_code"]}).status_code == 403
    assert client.get("/api/access/status", headers={"X-ARIA-Account": token}).json()["actor"] is None
    assert client.post("/api/access/login", json={"actor_id": caregiver, "pin": "654321"}).status_code == 401


def test_unconfigured_builtin_rejects_unlicensed_manifest(protected, tmp_path):
    client, app, gpu, mark = protected
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"reference": "other-person.wav", "synthetic": False, "redistribution_permitted": True}))
    app.state.settings.builtin_voice_manifest = manifest
    assert client.get("/api/voices").json()[0]["available"] is False
    assert client.post("/api/tts", json={"voice_id": "aria_builtin", "text": "hello"}).status_code == 503


def test_legacy_emotion_reference_cannot_bypass_assistive_authorization(protected):
    client, app, gpu, mark = protected
    voice = enroll_authorized(client)
    with app.state.db.session.begin() as session:
        session.add(EmotionReference(voice_id=voice, emotion="happy", model_version=app.state.settings.model_version,
            revision="legacy", latents=app.state.cipher.encrypt(json.dumps({**LATENTS, "model_fingerprint": FP}).encode())))
    response = client.post("/api/tts", json={"text": "hello", "voice_id": voice, "emotion": "happy"})
    assert response.status_code == 200
    assert response.headers["x-aria-emotion-method"] == "neutral_fallback"


def test_legacy_audio_migration_preserves_voice_and_runs_only_once(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, aria_key="x" * 48, require_auth=True, phrase_prewarm_enabled=False)
    headers = {"Authorization": "Bearer " + "x" * 48}
    first = create_app(settings, gpu=Model(), watermark_engine=Mark())
    with TestClient(first, headers=headers) as client:
        voice = enroll_authorized(client)
        with first.state.db.session.begin() as session:
            session.delete(session.get(RuntimeSetting, "protected_audio_cache_v4"))
            session.add(AudioCache(key="legacy", voice_id=voice, audio=b"old unprotected bytes"))
    second = create_app(settings, gpu=Model(), watermark_engine=Mark())
    with TestClient(second, headers=headers):
        with second.state.db.session.begin() as session:
            assert session.get(Voice, voice) is not None
            assert session.get(VoiceConsent, voice).active
            assert session.get(AudioCache, "legacy") is None
            session.add(AudioCache(key="new", voice_id=voice, audio=b"migration must not run again"))
    third = create_app(settings, gpu=Model(), watermark_engine=Mark())
    with TestClient(third, headers=headers):
        with third.state.db.session() as session:
            assert session.get(AudioCache, "new") is not None


def test_synthesis_uses_conditioning_fingerprint_even_when_health_changed():
    from app.services.gpu_client import GPUClient
    async def run():
        gpu = GPUClient(Settings(_env_file=None))
        gpu.model_fingerprint = "b" * 64
        async def request(method, path, **kwargs):
            assert kwargs["json"]["model_fingerprint"] == FP
            assert "authorization" not in kwargs["json"]
            return {"wav_b64": base64.b64encode(reference()).decode(), "sr": 22050}
        gpu.request = request
        try:
            await gpu.synthesize("hello", {**LATENTS, "model_fingerprint": FP, "authorization": {"private": True}}, 1)
        finally:
            await gpu.close()
    asyncio.run(run())


def test_phrase_text_remains_available_without_an_authorized_voice(protected):
    client, app, gpu, mark = protected
    voice = enroll_authorized(client)
    assert client.post(f"/api/voices/{voice}/revoke").status_code == 204
    bank = client.get("/api/phrases", params={"voice_id": ""})
    assert bank.status_code == 200
    assert bank.json()["voice_id"] is None
    assert bank.json()["items"] and all(not item["cached"] for item in bank.json()["items"])
