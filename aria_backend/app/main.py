import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import logging
import time

from cryptography.fernet import InvalidToken
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.formparsers import MultiPartParser
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import SecretStr

from .config import Settings, validate_colab_url
from .db import Database, RuntimeSetting, AudioCache, PhraseAudio
from sqlalchemy import delete
from .services.cache import AudioCacheService
from .services.crypto import load_cipher
from .services.errors import ServiceError
from .services.gpu_client import GPUClient
from .services.transliteration import Transliterator
from .services.voice_store import VoiceStore
from .services.phrases import PhraseStore
from .services.prediction import Predictor
from .services.phrase_warmer import PhraseWarmer
from .services.liveness import Liveness
from .services.watermark import Watermarker
from .services.emotion import EmotionService
from .services.languages import Languages
from .services.phrase_translation import PhraseTranslation
from .services.access import Access
from .services.model_identity import ModelIdentity
from .services.builtin_voice import BuiltinVoice

log = logging.getLogger("aria.backend")


class RequestGuard:
    def __init__(self, app, settings):
        self.app, self.settings, self.active = app, settings, 0
        self.upload_active = 0
        self.buckets = {}

    def budget(self, client, failed=False):
        now = time.monotonic()
        if len(self.buckets) >= 4096:
            self.buckets = {k: v for k, v in self.buckets.items() if v[0] > now}
            if len(self.buckets) >= 4096 and client not in self.buckets:
                return False
        expiry, requests, failures = self.buckets.get(client, (0, 0, 0))
        if expiry <= now:
            expiry, requests, failures = now + self.settings.rate_limit_window_seconds, 0, 0
        if requests >= self.settings.rate_limit_requests or failures >= self.settings.auth_failure_limit:
            return False
        self.buckets[client] = (expiry, requests + 1, failures + int(failed))
        return True

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        downstream_send = send
        async def hardened_send(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                names = {k.lower() for k, _ in response_headers}
                for key, value in ((b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"),
                                   (b"referrer-policy", b"no-referrer"), (b"x-frame-options", b"DENY")):
                    if key not in names:
                        response_headers.append((key, value))
                message = {**message, "headers": response_headers}
            await downstream_send(message)
        send = hardened_send
        async def reject(status, detail):
            await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)
        secret = self.settings.aria_key.get_secret_value()
        if self.settings.workflow_mode == "assistive" and len(secret) < 32:
            return await reject(503, "Initialize protected device settings with Start ARIA or configure_local.py")
        authenticated = not secret or hmac.compare_digest(headers.get(b"authorization", b""), ("Bearer " + secret).encode())
        client = (scope.get("client") or ("unknown", 0))[0]
        if not self.budget(client, failed=not authenticated):
            return await reject(429, "Request limit reached; wait a minute and try again")
        if not authenticated:
            return await reject(401, "Missing or invalid bearer token")
        origin = headers.get(b"origin", b"").decode("latin-1")
        same_origin = scope.get("scheme", "http") + "://" + headers.get(b"host", b"").decode("latin-1")
        if origin and origin != same_origin and origin not in self.settings.allowed_origins:
            return await reject(403, "Cross-origin requests are not allowed")
        if self.active >= self.settings.max_inflight:
            return await reject(429, "Backend busy; retry shortly")
        if headers.get(b"content-encoding", b"identity") != b"identity":
            return await reject(415, "Compressed request bodies are unsupported")
        try:
            size = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await reject(400, "Invalid Content-Length")
        upload = headers.get(b"content-type", b"").lower().startswith(b"multipart/form-data")
        limit = self.settings.max_request_bytes if upload else min(self.settings.max_request_bytes, self.settings.max_json_bytes)
        if size < 0 or size > limit:
            return await reject(413, "Request is too large")
        if upload and self.upload_active >= self.settings.max_parallel_uploads:
            return await reject(429, "Another recording is uploading or processing; retry shortly")
        self.active += 1
        self.upload_active += int(upload)
        started = False
        async def safe_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)
        try:
            deadline = time.monotonic() + self.settings.body_timeout_seconds
            received = 0
            async def bounded_receive():
                nonlocal received
                try:
                    packet = await asyncio.wait_for(receive(), max(0, deadline - time.monotonic()))
                except asyncio.TimeoutError:
                    raise StarletteHTTPException(408, "Request body timeout") from None
                if packet["type"] == "http.disconnect":
                    return packet
                part = packet.get("body", b"")
                received += len(part)
                if received > limit:
                    raise StarletteHTTPException(413, "Request is too large")
                return packet
            # Stream into the parser instead of retaining an additional full-body copy.
            await self.app(scope, bounded_receive, safe_send)
        except Exception as error:
            # Never log exception text/tracebacks: upstream messages may include user data.
            log.error(json.dumps({"event": "request_failed", "error_type": type(error).__name__}))
            if not started:
                await reject(500, "Local processing failed; check configuration or restore the encryption key")
        finally:
            self.active -= 1
            self.upload_active -= int(upload)


def create_app(settings=None, gpu=None, groq_client=None, verification_engine=None, watermark_engine=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.CRITICAL)
        state = app.state
        state.settings, state.data_lock = settings, asyncio.Lock()
        state.db = Database(settings.data_dir)
        try:
            state.cipher = load_cipher(settings)
            # Invalidate legacy unprotected audio once; never delete voice/profile records.
            with state.db.session.begin() as session:
                if session.get(RuntimeSetting, "protected_audio_cache_v4") is None:
                    session.execute(delete(AudioCache))
                    session.execute(delete(PhraseAudio))
                    session.add(RuntimeSetting(key="protected_audio_cache_v4", value=state.cipher.encrypt(b"1")))
            state.gpu = gpu or GPUClient(settings)
            state.identity = ModelIdentity(settings, state.db, state.cipher)
            state.access = Access(settings, state.db, state.cipher)
            state.builtin = BuiltinVoice(settings, state.db, state.cipher, state.gpu, state.identity)
            state.languages = Languages(settings, state.db, state.cipher)
            with state.db.session() as session:
                stored = session.get(RuntimeSetting, "colab")
                if stored:
                    data = json.loads(state.cipher.decrypt(stored.value))
                    state.gpu.configure(validate_colab_url(data["url"], settings.allow_insecure_colab), data["key"])
                groq = session.get(RuntimeSetting, "groq")
                if groq:
                    settings.groq_api_key = SecretStr(state.cipher.decrypt(groq.value).decode())
                    settings.llm_translit_enabled, settings.local_only = True, False
                    settings.translit_strategy = "api_first"
            state.transliterator = Transliterator(settings, state.db, state.cipher, groq_client)
            state.phrase_translator = PhraseTranslation(state.transliterator)
            state.liveness = Liveness(settings, state.db, state.cipher, verification_engine)
            state.watermarker = Watermarker(settings, watermark_engine)
            state.emotions = EmotionService(settings, state.db, state.cipher, state.gpu, state.liveness)
            state.voices = VoiceStore(settings, state.db, state.cipher, state.gpu, state.liveness)
            state.voices.access, state.voices.identity, state.voices.builtin = state.access, state.identity, state.builtin
            state.cache = AudioCacheService(settings, state.db, state.cipher)
            state.cache.emotions = state.emotions
            state.cache.identity, state.cache.watermarker, state.cache.builtin = state.identity, state.watermarker, state.builtin
            state.phrases = PhraseStore(settings, state.db, state.cipher, state.cache)
            state.phrases.seed()
            state.predictor = Predictor(settings, state.db, state.cipher)
            await state.predictor.rebuild()
            state.warmer = PhraseWarmer(state)
            state.warmer.start()
            yield
        finally:
            if hasattr(state, "warmer"):
                await state.warmer.close()
            if hasattr(state, "liveness"):
                state.liveness.revoke()
            if hasattr(state, "transliterator"):
                await state.transliterator.close()
            if hasattr(state, "gpu"):
                await state.gpu.close()
            state.db.close()

    app = FastAPI(title="A.R.I.A local backend", lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None, redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None)
    # Auth/limits precede multipart parsing. Keep original reference recordings in RAM.
    if hasattr(MultiPartParser, "spool_max_size"):
        MultiPartParser.spool_max_size = settings.max_request_bytes
    else:
        MultiPartParser.max_file_size = settings.max_request_bytes
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts, www_redirect=False)
    app.add_middleware(RequestGuard, settings=settings)

    @app.exception_handler(ServiceError)
    async def service_error(request, error):
        return JSONResponse({"detail": error.detail}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return JSONResponse({"detail": "Invalid request fields or values"}, status_code=422)

    @app.exception_handler(InvalidToken)
    async def invalid_key(request, error):
        return JSONResponse({"detail": "Encrypted data cannot be read; restore the original encryption key"}, status_code=500)

    from .api import admin, health, text, tts, voices, phrases, predict, safety, access
    for module in (admin, health, text, tts, voices, phrases, predict, safety, access):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()
