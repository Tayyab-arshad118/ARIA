import asyncio
import json

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.config import Settings
from app.db import Database, TextCache
from app.services.chunker import chunk_text
from app.services.errors import ServiceError
from app.services.transliteration import Transliterator
from app.services.urdu_normalizer import normalize_urdu, SMALL


@pytest.mark.parametrize("source,expected", [
    ("ي ك ة ـ ه", "ی ک ہ ہ"), ("مُجھے پَانی چَاہیے?", "مجھے پانی چاہیے؟"),
    ("2 گلاس", "دو گلاس"), ("۱۲۳", "ایک سو تئیس"), ("١٥", "پندرہ"),
    ("55", "پچپن"), ("100000", "ایک لاکھ"), ("10000000", "ایک کروڑ"),
    ("2.5", "دو اعشاریہ پانچ"), ("-3", "منفی تین"), ("007", "صفر صفر سات"),
    ("1,234", "ایک ہزار دو سو چونتیس"), ("کیا? ہاں, ٹھیک.", "کیا؟ ہاں، ٹھیک۔"),
])
def test_normalizer(source, expected):
    assert normalize_urdu(source) == expected
    assert len(SMALL) == 100


def test_chunker_boundaries_and_whole_words():
    text = "مجھے پانی چاہیے۔\nکیا آپ آئیں گے؟ شکریہ! " + "بہت " * 80
    chunks = chunk_text(text, 30)
    assert all(len(chunk) <= 30 for chunk in chunks)
    assert " ".join(chunks).split() == text.split()
    assert chunks[0] == "مجھے پانی چاہیے۔"
    assert chunk_text(" ") == []
    with pytest.raises(ServiceError):
        chunk_text("ا" * 181)


def setup_transliterator(tmp_path, handler, **overrides):
    settings = Settings(_env_file=None, data_dir=tmp_path, groq_api_key="test-key", local_only=False,
                        llm_translit_enabled=True, groq_backoff_seconds=0, **overrides)
    db = Database(tmp_path)
    cipher = Fernet(Fernet.generate_key())
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Transliterator(settings, db, cipher, client)


def run_convert(service, text):
    async def run():
        try:
            first = await service.convert(text)
            second = await service.convert(text)
            assert second == first
            return first
        finally:
            await service.close()
            service.db.close()
    return asyncio.run(run())


def test_dictionary_and_variants_without_network(tmp_path):
    def forbidden(request):
        pytest.fail("Dictionary matches should not call Groq")
    service = setup_transliterator(tmp_path, forbidden)
    assert len(service.dictionary) >= 300
    assert run_convert(service, "mujhy paani chahye")["urdu"] == "مجھے پانی چاہیے"


@pytest.mark.parametrize("failure", ["offline", "garbage", "empty", "429", "401", "missing-digits"])
def test_transliteration_fallback_chain(tmp_path, failure):
    calls = []
    def handler(request):
        calls.append(request)
        if failure == "offline":
            raise httpx.ConnectError("offline", request=request)
        if failure in {"429", "401"}:
            return httpx.Response(int(failure))
        content = {"garbage": "Here is your translation", "empty": "", "missing-digits": "مجھے پانی چاہیے"}[failure]
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    service = setup_transliterator(tmp_path, handler)
    result = run_convert(service, "mujhe zqwert 2")
    assert result["method_used"] == "rules" and result["urdu"].startswith("مجھے")
    assert len(calls) == (2 if failure == "429" else 1)


def test_llm_success_and_encrypted_cache(tmp_path):
    def handler(request):
        body = json.loads(request.content)
        assert body["reasoning_effort"] == "low" and body["max_completion_tokens"] == 512
        assert body["temperature"] == 0 and len(body["messages"]) == 42
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"choices": [{"message": {"content": "مجھے کتاب چاہیے"}}]})
    service = setup_transliterator(tmp_path, handler)
    result = run_convert(service, "mujhe ktaab chahiye")
    assert result["method_used"] == "llm"
    with service.db.session() as session:
        stored = session.scalar(select(TextCache))
        assert "مجھے".encode() not in stored.result


@pytest.mark.parametrize("policy", ["local", "disabled", "missing-key"])
def test_privacy_switches_skip_groq(tmp_path, policy):
    service = setup_transliterator(tmp_path, lambda request: pytest.fail("Network disabled"))
    if policy == "local":
        service.settings.local_only = True
    elif policy == "disabled":
        service.settings.llm_translit_enabled = False
    else:
        from pydantic import SecretStr
        service.settings.groq_api_key = SecretStr("")
    assert run_convert(service, "newword")["method_used"] == "rules"


def test_urdu_passthrough_and_decimal_dictionary(tmp_path):
    service = setup_transliterator(tmp_path, lambda request: pytest.fail("No network expected"))
    async def run():
        assert (await service.convert("مجھے پانی چاہیے"))["method_used"] == "passthrough"
        result = await service.convert("mujhe 2.5 glass pani\nchahiye")
        assert "2.5" in result["urdu"] and "\n" in result["urdu"]
        await service.close()
        service.db.close()
    asyncio.run(run())
