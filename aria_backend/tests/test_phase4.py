import asyncio
from collections import Counter
import json
import statistics
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import Phrase, PhraseAudio, SpokenHistory, Voice
from app.main import create_app
from app.services.prediction import Predictor, build_index
from test_api import FakeGPU, reference


@pytest.fixture
def bank(tmp_path):
    settings = Settings(_env_file=None, workflow_mode="research", watermark_policy="research_unprotected", data_dir=tmp_path, phrase_prewarm_enabled=False)
    gpu = FakeGPU()
    app = create_app(settings, gpu=gpu)
    with TestClient(app) as client:
        yield client, app, gpu


def enroll(client):
    result = client.post("/api/voices", files={"file": ("ref.wav", reference())}, data={"name": "test"})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def test_sixty_seeds_categories_and_crud_are_encrypted(bank):
    client, app, gpu = bank
    response = client.get("/api/phrases").json()
    assert response["total"] == 60 and response["ready"] == 0
    assert Counter(p["category"] for p in response["items"]) == dict.fromkeys(
        ["needs", "medical", "family", "greetings", "custom"], 12)
    payload = {"roman": "privatecode nectarword", "urdu": "مجھے پانی چاہیے", "category": "custom"}
    result = client.post("/api/phrases", json=payload)
    assert result.status_code == 201
    identifier = result.json()["id"]
    assert "nectarword" in client.get("/api/predict", params={"prefix": "privatecode "}).json()["suggestions"]
    with app.state.db.session() as session:
        stored = session.get(Phrase, identifier)
        assert b"privatecode" not in stored.content
        assert json.loads(app.state.cipher.decrypt(stored.content)) == payload
    assert client.patch(f"/api/phrases/{identifier}", json={"favorite": True}).status_code == 200
    assert client.get("/api/phrases", params={"favorites": True}).json()["items"][0]["id"] == identifier
    assert client.patch(f"/api/phrases/{identifier}", json={"roman": "newcode newword"}).status_code == 200
    assert "nectarword" not in client.get("/api/predict", params={"prefix": "privatecode n"}).json()["suggestions"]
    assert client.delete(f"/api/phrases/{identifier}").status_code == 204
    assert client.patch(f"/api/phrases/{identifier}", json={"favorite": False}).status_code == 404


@pytest.mark.parametrize("payload", [{"roman": "", "urdu": "پانی"}, {"roman": "x", "urdu": "English"},
    {"roman": "پانی", "urdu": "پانی"}, {"roman": "x", "urdu": "پانی", "category": "bad"}])
def test_phrase_validation(bank, payload):
    assert bank[0].post("/api/phrases", json=payload).status_code == 422


def test_voice_speed_and_text_changes_invalidate_audio(bank):
    client, app, gpu = bank
    first_voice = enroll(client)
    phrase = client.get("/api/phrases").json()["items"][0]
    route = f'/api/phrases/{phrase["id"]}/speak'
    first = client.post(route, json={"voice_id": first_voice})
    assert first.status_code == 200 and first.headers["x-audio-cache"] == "miss"
    second = client.post(route, json={"voice_id": first_voice})
    assert second.content == first.content and second.headers["x-audio-cache"] == "hit"
    assert len(gpu.calls) == 1
    assert client.get("/api/phrases", params={"recent": True}).json()["items"][0]["uses"] == 2
    other_voice = enroll(client)
    assert client.post(route, json={"voice_id": other_voice}).headers["x-audio-cache"] == "miss"
    assert client.post(route, json={"voice_id": first_voice, "speed": 1.2}).headers["x-audio-cache"] == "miss"
    assert client.patch(f'/api/phrases/{phrase["id"]}', json={"urdu": "مجھے مدد چاہیے"}).status_code == 200
    assert client.post(route, json={"voice_id": first_voice}).headers["x-audio-cache"] == "miss"
    with app.state.db.session() as session:
        row = session.scalar(select(PhraseAudio))
        assert not row.audio.startswith(b"RIFF")
        assert app.state.cipher.decrypt(row.audio).startswith(b"RIFF")
    app.state.settings.model_version = "next-model"
    assert client.post(route, json={"voice_id": first_voice}).status_code == 409
    new_voice = enroll(client)
    assert client.post(route, json={"voice_id": new_voice}).headers["x-audio-cache"] == "miss"


def test_history_learning_failure_and_delete_all(bank):
    client, app, gpu = bank
    voice = enroll(client)
    assert client.post("/api/tts", json={"text": "newcode nectarword", "voice_id": voice}).status_code == 200
    assert client.get("/api/predict", params={"prefix": "newcode "}).json()["suggestions"][0] == "nectarword"
    with app.state.db.session() as session:
        assert b"newcode" not in session.scalar(select(SpokenHistory)).text
    gpu.offline = True
    assert client.post("/api/tts", json={"text": "othercode otherword"}).status_code == 503
    assert "otherword" not in client.get("/api/predict", params={"prefix": "othercode "}).json()["suggestions"]
    custom = client.post("/api/phrases", json={"roman": "customcode customword", "urdu": "پانی"}).json()
    client.patch(f'/api/phrases/{custom["id"]}', json={"favorite": True})
    assert client.delete("/api/voices/all").status_code == 200
    data = client.get("/api/phrases").json()
    assert data["total"] == 60 and not any(p["favorite"] or p["last_used"] for p in data["items"])
    with app.state.db.session() as session:
        assert session.scalar(select(SpokenHistory)) is None
        assert session.scalar(select(PhraseAudio)) is None
    assert "nectarword" not in client.get("/api/predict", params={"prefix": "newcode "}).json()["suggestions"]


def test_seed_deletion_and_history_survive_restart(tmp_path):
    settings = Settings(_env_file=None, workflow_mode="research", watermark_policy="research_unprotected", data_dir=tmp_path, phrase_prewarm_enabled=False)
    with TestClient(create_app(settings, gpu=FakeGPU())) as client:
        voice = enroll(client)
        assert client.delete("/api/phrases/needs-1").status_code == 204
        client.post("/api/tts", json={"text": "newcode nectarword", "voice_id": voice})
    with TestClient(create_app(settings, gpu=FakeGPU())) as client:
        assert client.get("/api/phrases").json()["total"] == 59
        assert client.get("/api/predict", params={"prefix": "newcode "}).json()["suggestions"][0] == "nectarword"
        client.delete(f"/api/voices/{voice}")
        assert "nectarword" not in client.get("/api/predict", params={"prefix": "newcode "}).json()["suggestions"]


def test_partial_words_trigrams_and_bounded_history(bank):
    client, app, gpu = bank
    enroll(client)
    assert "pani" in client.get("/api/predict", params={"prefix": "mujhe pa"}).json()["suggestions"]
    assert "chahiye" in client.get("/api/predict", params={"prefix": "mujhe pani "}).json()["suggestions"]
    assert client.get("/api/predict", params={"prefix": "مجھے"}).json()["suggestions"] == []
    app.state.settings.prediction_history_limit = 1
    client.post("/api/tts", json={"text": "firstcode firstword"})
    client.post("/api/tts", json={"text": "secondcode secondword"})
    assert "firstword" not in client.get("/api/predict", params={"prefix": "firstcode "}).json()["suggestions"]
    assert client.get("/api/predict", params={"prefix": "secondcode "}).json()["suggestions"][0] == "secondword"


def test_predictor_lookup_budget(bank):
    client, app, gpu = bank
    durations = []
    for i in range(1000):
        start = time.perf_counter()
        suggestions = app.state.predictor.suggest("mujhe pani ")
        durations.append((time.perf_counter() - start) * 1000)
        assert len(suggestions) <= 5
    assert statistics.quantiles(durations, n=100)[94] < 50
    response = client.get("/api/predict", params={"prefix": "mujhe "})
    assert float(response.headers["x-prediction-ms"]) < 50


def two_seeds(tmp_path):
    path = tmp_path / "seeds.json"
    path.write_text(json.dumps([
        {"id": "one", "roman": "mujhe pani chahiye", "urdu": "مجھے پانی چاہیے", "category": "needs"},
        {"id": "two", "roman": "mujhe madad chahiye", "urdu": "مجھے مدد چاہیے", "category": "needs"},
    ], ensure_ascii=False), encoding="utf-8")
    return path


def test_background_warming_cache_hits_and_deletion_race(tmp_path):
    async def run():
        settings = Settings(_env_file=None, workflow_mode="research", watermark_policy="research_unprotected", data_dir=tmp_path / "db", phrase_seed_path=two_seeds(tmp_path),
                            phrase_prewarm_enabled=False)
        gpu = FakeGPU()
        app = create_app(settings, gpu=gpu)
        async with app.router.lifespan_context(app):
            state = app.state
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://local") as client:
                voice = (await client.post("/api/voices", files={"file": ("ref.wav", reference())}, data={"name": "test"})).json()["id"]
                # Cache the first phrase, then deliberately block GPU warming of the second.
                assert (await client.post("/api/phrases/one/speak", json={})).status_code == 200
                entered, release = asyncio.Event(), asyncio.Event()
                original = gpu.synthesize
                async def slow(*args, **kwargs):
                    entered.set()
                    await release.wait()
                    return await original(*args, **kwargs)
                gpu.synthesize = slow
                worker = asyncio.create_task(state.warmer.warm_once())
                await asyncio.wait_for(entered.wait(), 2)
                cached = await asyncio.wait_for(client.post("/api/phrases/one/speak", json={}), 2)
                assert cached.headers["x-audio-cache"] == "hit"
                predicted = await asyncio.wait_for(client.get("/api/predict", params={"prefix": "mujhe "}), 1)
                assert predicted.status_code == 200
                assert (await client.delete("/api/voices/all")).status_code == 200
                release.set()
                await worker
                with state.db.session() as session:
                    assert session.scalar(select(PhraseAudio)) is None
                    assert session.scalar(select(Voice)) is None
                    assert session.scalar(select(SpokenHistory)) is None
    asyncio.run(run())


def test_automatic_warming_and_regeneration_after_edit(tmp_path):
    async def run():
        settings = Settings(_env_file=None, workflow_mode="research", watermark_policy="research_unprotected", data_dir=tmp_path / "db", phrase_seed_path=two_seeds(tmp_path),
                            phrase_prewarm_enabled=True)
        gpu = FakeGPU()
        app = create_app(settings, gpu=gpu)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://local") as client:
                await client.post("/api/voices", files={"file": ("ref.wav", reference())}, data={"name": "test"})
                async def ready():
                    for _ in range(100):
                        data = (await client.get("/api/phrases")).json()
                        if data["ready"] == 2:
                            return
                        await asyncio.sleep(0.02)
                    pytest.fail("Warm-up did not finish")
                await ready()
                assert len(gpu.calls) == 2
                with app.state.db.session() as session:
                    assert session.scalar(select(SpokenHistory)) is None
                await client.patch("/api/phrases/one", json={"urdu": "مجھے دوا چاہیے"})
                await ready()
                assert len(gpu.calls) == 3
    asyncio.run(run())
