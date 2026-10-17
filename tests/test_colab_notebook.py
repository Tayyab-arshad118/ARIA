"""Run the actual notebook API cells with a CPU-only fake XTTS/CUDA runtime."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import io
import json
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
from types import ModuleType, SimpleNamespace

import nbformat
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient


NOTEBOOK = Path(__file__).resolve().parents[1] / "colab" / "ARIA_Colab_GPU.ipynb"


def source(name):
    book = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return next(c["source"] for c in book["cells"] if c["id"] == name)


class Tensor:
    def __init__(self, value):
        self.value = np.asarray(value)

    def to(self, *args, **kwargs):
        return self

    def unsqueeze(self, axis):
        return Tensor(np.expand_dims(self.value, axis))

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.value


class FakeModel:
    def __init__(self):
        self.tokenizer = SimpleNamespace(encode=lambda text, lang: list(range(len(text))))
        self.calls = []
        self.active = 0
        self.peak = 0
        self.mutex = threading.Lock()
        self.failure = None

    def get_gpt_cond_latents(self, audio, sr, **kwargs):
        assert audio.value.ndim == 2 and sr > 0
        return Tensor(np.ones((1, 32, 8), dtype=np.float32))

    def get_speaker_embedding(self, audio, sr):
        return Tensor(np.ones((1, 4, 1), dtype=np.float32))

    def inference(self, **kwargs):
        if self.failure:
            raise self.failure
        with self.mutex:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(0.015)
            self.calls.append(kwargs)
            return {"wav": np.sin(np.arange(2400) * 0.1).astype(np.float32) * 0.1}
        finally:
            with self.mutex:
                self.active -= 1


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setenv("API_KEY", secrets.token_urlsafe(32))
    monkeypatch.setenv("LOCK_TIMEOUT_SECONDS", "5")
    module = ModuleType("aria_test_runtime")
    monkeypatch.setitem(sys.modules, module.__name__, module)
    ns = module.__dict__
    exec(compile(source("config"), "notebook-config", "exec"), ns)
    cuda = SimpleNamespace(
        empty_calls=0, get_device_name=lambda _: "Mock T4", OutOfMemoryError=type("MockOOM", (RuntimeError,), {})
    )

    def empty_cache():
        cuda.empty_calls += 1

    cuda.empty_cache = empty_cache
    ns.update(
        torch=SimpleNamespace(cuda=cuda, no_grad=nullcontext, from_numpy=Tensor),
        model=FakeModel(), GPT_CHANNELS=8, SPEAKER_DIM=4, MAX_MODEL_TEXT_TOKENS=400, OUTPUT_SR=24000,
        SUPPORTED_LANGUAGES=["ar", "en"],
    )
    exec(compile(source("api"), "notebook-api", "exec"), ns)
    with TestClient(ns["app"], raise_server_exceptions=False) as client:
        yield SimpleNamespace(ns=ns, client=client, headers={"x-api-key": ns["API_KEY"]}, cuda=cuda)


def npy(value):
    output = io.BytesIO()
    np.save(output, value, allow_pickle=False)
    return base64.b64encode(output.getvalue()).decode("ascii")


def payload():
    return {
        "text": "مجھے پانی چاہیے۔",
        "gpt_cond_latent": npy(np.ones((1, 32, 8), dtype=np.float32)),
        "speaker_embedding": npy(np.ones((1, 4, 1), dtype=np.float32)),
    }


def wav(seconds=6, sr=22050, channels=1, silent=False):
    samples = np.zeros(int(seconds * sr)) if silent else np.sin(np.arange(int(seconds * sr)) * 0.1) * 0.1
    if channels > 1:
        samples = np.repeat(samples[:, None], channels, axis=1)
    output = io.BytesIO()
    sf.write(output, samples, sr, format="WAV", subtype="PCM_16")
    return output.getvalue()


def test_notebook_schema_python_and_no_saved_outputs():
    book = nbformat.read(NOTEBOOK, as_version=4)
    nbformat.validate(book)
    for cell in book.cells:
        if cell.cell_type == "code":
            compile(cell.source, cell.id, "exec")
            assert cell.execution_count is None and cell.outputs == []
    assert book.metadata.colab.private_outputs is True


@pytest.mark.parametrize("route,method", [("/health", "get"), ("/latents", "post"), ("/synthesize", "post")])
def test_all_endpoints_require_key(runtime, route, method):
    request = getattr(runtime.client, method)
    assert request(route).status_code == 401
    assert request(route, headers={"x-api-key": "wrong"}).status_code == 401


def test_health_contract(runtime):
    assert runtime.client.get("/health", headers=runtime.headers).json() == {
        "ok": True, "gpu": "Mock T4", "lang": "ar", "languages": ["ar", "en"]
    }


def test_reference_to_synthesis_round_trip_and_no_spool(runtime, monkeypatch):
    import starlette.formparsers

    # Force upload above Starlette's usual 1 MiB disk-spool threshold.
    original = starlette.formparsers.SpooledTemporaryFile
    handles = []

    def tracked(*args, **kwargs):
        handle = original(*args, **kwargs)
        handles.append(handle)
        return handle

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", tracked)
    reference = wav(seconds=7, sr=48000, channels=2)
    assert len(reference) > 1024 * 1024
    result = runtime.client.post("/latents", headers=runtime.headers, files={"file": ("ref.wav", reference, "audio/wav")})
    assert result.status_code == 200, result.text
    assert handles and all(h.closed and not h._rolled for h in handles)
    latent = result.json()
    assert np.load(io.BytesIO(base64.b64decode(latent["gpt_cond_latent"])), allow_pickle=False).shape == (1, 32, 8)
    spoken = runtime.client.post("/synthesize", headers=runtime.headers, json={"text": "مجھے پانی چاہیے۔", **latent})
    assert spoken.status_code == 200, spoken.text
    audio, rate = sf.read(io.BytesIO(base64.b64decode(spoken.json()["wav_b64"])))
    assert rate == spoken.json()["sr"] == 24000
    assert len(audio) == 2400
    assert runtime.ns["model"].calls[0]["language"] == "ar"
    assert runtime.cuda.empty_calls == 2


@pytest.mark.parametrize("reference", [b"invalid", wav(seconds=1), wav(silent=True), wav(sr=4000), wav(channels=3)],
                         ids=["invalid", "short", "silent", "bad-rate", "bad-channels"])
def test_reject_invalid_reference(runtime, reference):
    response = runtime.client.post("/latents", headers=runtime.headers, files={"file": ("ref.wav", reference)})
    assert response.status_code == 422
    assert not runtime.ns["model"].calls


def test_upload_byte_limit(runtime):
    runtime.ns["SETTINGS"]["MAX_WAV_BYTES"] = 100
    assert runtime.client.post("/latents", headers=runtime.headers, files={"file": ("ref.wav", wav())}).status_code == 413


@pytest.mark.parametrize("field,value", [
    ("text", " "), ("text", "ا" * 181), ("speed", 0.0), ("temperature", 2.0),
    ("gpt_cond_latent", "not-base64"),
    ("gpt_cond_latent", npy(np.ones((1, 32, 7), dtype=np.float32))),
    ("gpt_cond_latent", npy(np.ones((1, 32, 8), dtype=np.int32))),
    ("speaker_embedding", npy(np.full((1, 4, 1), np.nan, dtype=np.float32))),
], ids=["blank", "long", "speed", "temperature", "base64", "shape", "dtype", "nan"])
def test_synthesis_validation(runtime, field, value):
    body = payload()
    body[field] = value
    response = runtime.client.post("/synthesize", headers=runtime.headers, json=body)
    assert response.status_code == 422, response.text
    assert not runtime.ns["model"].calls
    assert body["gpt_cond_latent"] not in response.text
    assert body["text"] not in response.text or body["text"].isspace()


def test_npy_header_cannot_force_large_allocation(runtime, monkeypatch):
    stream = io.BytesIO()
    np.lib.format.write_array_header_1_0(stream, {"shape": (1, 10**12, 8), "fortran_order": False, "descr": "<f4"})
    body = payload()
    body["gpt_cond_latent"] = base64.b64encode(stream.getvalue()).decode()

    def forbidden_load(*args, **kwargs):
        pytest.fail("Malformed header reached np.load")

    monkeypatch.setattr(np, "load", forbidden_load)
    assert runtime.client.post("/synthesize", headers=runtime.headers, json=body).status_code == 422


def test_pickle_rejected_before_load(runtime, monkeypatch):
    stream = io.BytesIO()
    np.save(stream, np.array([{"not": "a numeric latent"}], dtype=object), allow_pickle=True)
    body = payload()
    body["gpt_cond_latent"] = base64.b64encode(stream.getvalue()).decode()
    monkeypatch.setattr(np, "load", lambda *args, **kwargs: pytest.fail("Pickled input reached np.load"))
    assert runtime.client.post("/synthesize", headers=runtime.headers, json=body).status_code == 422


def test_header_body_limit(runtime):
    headers = {**runtime.headers, "content-length": str(runtime.ns["SETTINGS"]["MAX_REQUEST_BYTES"] + 1)}
    assert runtime.client.post("/synthesize", headers=headers, content=b"{}").status_code == 413


def test_chunked_body_limit_without_content_length(runtime):
    ns = runtime.ns
    ns["SETTINGS"]["MAX_REQUEST_BYTES"] = 16
    sent = []
    messages = iter([
        {"type": "http.request", "body": b"x" * 10, "more_body": True},
        {"type": "http.request", "body": b"x" * 10, "more_body": False},
    ])

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": "/latents", "headers": [(b"x-api-key", ns["API_KEY"].encode())]}
    asyncio.run(ns["app"](scope, receive, send))
    assert sent[0]["status"] == 413
    assert ns["app"].active == 0


def test_busy_gate(runtime):
    runtime.ns["app"].active = runtime.ns["SETTINGS"]["MAX_INFLIGHT"]
    assert runtime.client.get("/health", headers=runtime.headers).status_code == 429


def test_lock_timeout(runtime):
    runtime.ns["SETTINGS"]["LOCK_TIMEOUT_SECONDS"] = 0.1
    lock = runtime.ns["gpu_lock"]
    lock.acquire()
    try:
        assert runtime.client.post("/synthesize", headers=runtime.headers, json=payload()).status_code == 503
    finally:
        lock.release()


def test_gpu_requests_are_serialized(runtime):
    def call(_):
        return runtime.client.post("/synthesize", headers=runtime.headers, json=payload()).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(call, range(2))) == [200, 200]
    assert runtime.ns["model"].peak == 1
    assert runtime.cuda.empty_calls == 2


@pytest.mark.parametrize("failure_kind,status", [("oom", 503), ("internal", 500)])
def test_failure_releases_lock_cleans_gpu_and_hides_details(runtime, failure_kind, status, capsys):
    secret_marker = "private sentence or credentials"
    error_type = runtime.cuda.OutOfMemoryError if failure_kind == "oom" else RuntimeError
    runtime.ns["model"].failure = error_type(secret_marker)
    response = runtime.client.post("/synthesize", headers=runtime.headers, json=payload())
    assert response.status_code == status
    assert secret_marker not in response.text
    assert secret_marker not in capsys.readouterr().err
    assert not runtime.ns["gpu_lock"].locked()
    assert runtime.cuda.empty_calls == 1


def test_selected_model_language_is_forwarded_and_unknown_rejected(runtime):
    body = {**payload(), "language": "en", "text": "Hello from ARIA."}
    response = runtime.client.post("/synthesize", headers=runtime.headers, json=body)
    assert response.status_code == 200, response.text
    assert runtime.ns["model"].calls[-1]["language"] == "en"
    body["language"] = "zz"
    assert runtime.client.post("/synthesize", headers=runtime.headers, json=body).status_code == 422
    assert len(runtime.ns["model"].calls) == 1


def test_token_limit(runtime):
    runtime.ns["model"].tokenizer.encode = lambda text, lang: [0] * 400
    assert runtime.client.post("/synthesize", headers=runtime.headers, json=payload()).status_code == 422
    assert not runtime.ns["model"].calls


def test_real_uvicorn_start_restart_and_shutdown_with_fake_tunnel(runtime, monkeypatch):
    import httpx
    import subprocess

    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    ns = runtime.ns
    ns["SETTINGS"].update(PORT=port, STARTUP_TIMEOUT_SECONDS=5, TUNNEL_TIMEOUT_SECONDS=5)
    real_get = httpx.get
    processes = []

    class FakeTunnel:
        def __init__(self, *args, **kwargs):
            self.stdout = io.StringIO(f"Tunnel at https://aria-test-{len(processes)}.trycloudflare.com\n")
            self.code = None
            processes.append(self)

        def poll(self):
            return self.code

        def terminate(self):
            self.code = 0

        def wait(self, **kwargs):
            return self.code

    def local_transport(url, **kwargs):
        if "trycloudflare.com" in url:
            url = f"http://127.0.0.1:{port}/health"
        return real_get(url, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", FakeTunnel)
    monkeypatch.setattr(httpx, "get", local_transport)
    try:
        exec(compile(source("serve"), "notebook-serve", "exec"), ns)
        first_thread = ns["server_thread"]
        assert first_thread.is_alive()
        assert ns["os"].environ["COLAB_URL"].endswith("aria-test-0.trycloudflare.com")
        exec(compile(source("serve"), "notebook-serve", "exec"), ns)
        assert not first_thread.is_alive()
        assert ns["server_thread"].is_alive()
        assert processes[0].poll() == 0
        assert ns["os"].environ["COLAB_URL"].endswith("aria-test-1.trycloudflare.com")
    finally:
        if "stop_server" in ns:
            ns["stop_server"]()
    assert not ns["server_thread"].is_alive()
    assert processes[-1].poll() == 0
    assert "COLAB_URL" not in ns["os"].environ
