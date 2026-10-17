import asyncio
from datetime import datetime, timedelta, timezone
import json

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import select

from app.config import Settings
from app.db import Database, TextCache
from app.main import create_app, RequestGuard
from app.services.transliteration import Transliterator
from test_api import FakeGPU


def test_chunked_multipart_and_json_limits_without_content_length(tmp_path):
    async def run():
        settings = Settings(_env_file=None, data_dir=tmp_path, max_upload_bytes=1024,
                            max_request_bytes=2048, max_json_bytes=1024, phrase_prewarm_enabled=False)
        app = create_app(settings, gpu=FakeGPU())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                async def large_json():
                    yield b'{"text":"' + b'x' * 600
                    yield b'x' * 600 + b'"}'
                response = await client.post("/api/transliterate", content=large_json(), headers={"Content-Type": "application/json"})
                assert response.status_code == 413, response.text
                async def large_upload():
                    yield b'--part\r\nContent-Disposition: form-data; name="file"; filename="voice.wav"\r\n\r\n'
                    yield b'x' * 1500
                    yield b'x' * 1500 + b'\r\n--part--\r\n'
                response = await client.post("/api/voices", content=large_upload(), headers={"Content-Type": "multipart/form-data; boundary=part"})
                assert response.status_code == 413, response.text
                assert (await client.get("/api/health")).status_code == 200
    asyncio.run(run())


def test_upload_admission_slot_releases_after_completion(tmp_path):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def app(scope, receive, send):
            entered.set()
            await release.wait()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})
        guard = RequestGuard(app, Settings(_env_file=None, data_dir=tmp_path))
        scope = {"type": "http", "headers": [(b"content-type", b"multipart/form-data; boundary=x")]}
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = []
        async def send(message):
            sent.append(message)
        first = asyncio.create_task(guard(scope, receive, send))
        await entered.wait()
        await guard(scope, receive, send)
        assert sent[0]["status"] == 429 and guard.upload_active == 1
        release.set()
        await first
        assert guard.active == guard.upload_active == 0
    asyncio.run(run())


def test_secure_host_auth_origins_headers_and_hidden_docs(tmp_path):
    token = "a" * 48
    settings = Settings(_env_file=None, data_dir=tmp_path, aria_key=token, require_auth=True,
                        allowed_hosts=["testserver"], phrase_prewarm_enabled=False)
    with TestClient(create_app(settings, gpu=FakeGPU())) as client:
        response = client.get("/api/health")
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        auth = {"Authorization": "Bearer " + token}
        assert client.get("/api/health", headers=auth).status_code == 200
        assert client.get("/api/health", headers={**auth, "Host": "evil.example"}).status_code == 400
        assert client.delete("/api/voices/all", headers={**auth, "Origin": "https://evil.example"}).status_code == 403
        assert client.get("/api/health", headers={**auth, "Origin": "http://testserver"}).status_code == 200
        assert client.get("/docs", headers=auth).status_code == 404
        assert client.get("/openapi.json", headers=auth).status_code == 404


def test_rate_limits_include_failed_authentication(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, aria_key="a" * 48, require_auth=True,
                        auth_failure_limit=2, phrase_prewarm_enabled=False)
    with TestClient(create_app(settings, gpu=FakeGPU())) as client:
        assert client.get("/api/health").status_code == 401
        assert client.get("/api/health").status_code == 401
        assert client.get("/api/health").status_code == 429
    settings.rate_limit_requests, settings.auth_failure_limit = 2, 12
    with TestClient(create_app(settings, gpu=FakeGPU())) as client:
        auth = {"Authorization": "Bearer " + "a" * 48}
        assert client.get("/api/health", headers=auth).status_code == 200
        assert client.get("/api/health", headers=auth).status_code == 200
        assert client.get("/api/health", headers=auth).status_code == 429


@pytest.mark.parametrize("values", [{"require_auth": True}, {"require_auth": True, "aria_key": "short"},
    {"host": "0.0.0.0"}, {"aria_key": "invalid key"}])
def test_unsafe_configuration_is_rejected(values):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **values)


@pytest.mark.parametrize("text,expected", [("me thk hu", "میں ٹھیک ہوں"),
    ("me ghar me hu", "میں گھر میں ہوں"), ("mjy pani chahiye", "مجھے پانی چاہیے"),
    ("me theek ni hu", "میں ٹھیک نہیں ہوں"), ("mujhe wheelchair chahiye", "مجھے وہیل چیئر چاہیے")])
def test_common_shorthand_and_larger_dictionary(tmp_path, text, expected):
    async def run():
        settings = Settings(_env_file=None, data_dir=tmp_path)
        db = Database(tmp_path)
        service = Transliterator(settings, db, Fernet(Fernet.generate_key()),
            httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail("Local-only must not call API"))))
        try:
            assert len(service.dictionary) > 2500
            response = await service.convert(text)
            assert response["urdu"] == expected and response["method_used"] == "dictionary"
        finally:
            await service.close()
            db.close()
    asyncio.run(run())


def test_api_first_uses_groq_even_for_known_words_and_retries_stale_fallback(tmp_path):
    requests = []
    healthy = [False]
    def handler(request):
        requests.append(request)
        if not healthy[0]:
            return httpx.Response(503)
        return httpx.Response(200, json={"choices": [{"message": {"content": "میں ٹھیک ہوں"}}]})
    async def run():
        settings = Settings(_env_file=None, data_dir=tmp_path, local_only=False, llm_translit_enabled=True,
                            groq_api_key="dummy", translit_strategy="api_first")
        db = Database(tmp_path)
        service = Transliterator(settings, db, Fernet(Fernet.generate_key()), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            first = await service.convert("me thk hu")
            assert first["method_used"] == "dictionary" and len(requests) == 1
            assert (await service.convert("me thk hu"))["method_used"] == "dictionary"
            assert len(requests) == 1
            with db.session.begin() as session:
                session.scalar(select(TextCache)).created_at = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
            healthy[0] = True
            assert (await service.convert("me thk hu"))["method_used"] == "llm"
            assert len(requests) == 2
            assert (await service.convert("me thk hu"))["method_used"] == "llm" and len(requests) == 2
        finally:
            await service.close()
            db.close()
    asyncio.run(run())


def test_oversized_groq_response_falls_back_without_echoing_body(tmp_path):
    async def run():
        settings = Settings(_env_file=None, data_dir=tmp_path, local_only=False, llm_translit_enabled=True,
                            groq_api_key="dummy", translit_strategy="api_first", groq_max_response_bytes=1024)
        db = Database(tmp_path)
        service = Transliterator(settings, db, Fernet(Fernet.generate_key()), httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 1025))))
        try:
            assert (await service.convert("me thk hu"))["method_used"] == "dictionary"
        finally:
            await service.close()
            db.close()
    asyncio.run(run())
