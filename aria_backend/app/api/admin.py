import json

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from ..config import validate_colab_url
from ..db import RuntimeSetting
from ..services.errors import ServiceError
from ..services.gpu_client import GPUClient
from fastapi.responses import JSONResponse

router = APIRouter()


class ConnectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    colab_url: str = Field(min_length=1, max_length=2048)
    colab_api_key: SecretStr
    groq_api_key: SecretStr | None = None


@router.post("/admin/connect")
async def connect(body: ConnectInput, request: Request):
    state = request.app.state
    state.access.patient(request)
    try:
        url = validate_colab_url(body.colab_url, state.settings.allow_insecure_colab)
        key = body.colab_api_key.get_secret_value().strip()
        groq = body.groq_api_key.get_secret_value().strip() if body.groq_api_key else ""
        if not url or not key or any(not value.isascii() or any(c.isspace() for c in value) or len(value) > 512 for value in (key, groq) if value):
            raise ValueError()
    except ValueError:
        return JSONResponse({"code": "invalid_connection"}, status_code=400)
    # Test a separate client: a failed setup must preserve the working connection.
    probe = GPUClient(state.settings.model_copy(update={"colab_url": url, "colab_api_key": SecretStr(key)}))
    try:
        remote = await probe.health()
        if not remote.get("languages"):
            return JSONResponse({"code": "notebook_update_required"}, status_code=409)
    except ServiceError as error:
        code = ("colab_key_rejected" if "rejected the API key" in error.detail else
                "colab_response_invalid" if error.status == 502 else
                "model_mismatch" if "configuration" in error.detail else "colab_unreachable")
        return JSONResponse({"code": code}, status_code=400)
    finally:
        await probe.close()
    async with state.data_lock:
        state.access.patient(request)
        state.identity.observe(remote)
        state.languages.update(remote)
        with state.db.session.begin() as session:
            session.merge(RuntimeSetting(key="colab", value=state.cipher.encrypt(json.dumps({"url": url, "key": key}).encode())))
            if groq:
                session.merge(RuntimeSetting(key="groq", value=state.cipher.encrypt(groq.encode())))
        state.gpu.configure(url, key)
        if groq:
            state.settings.groq_api_key = SecretStr(groq)
            state.settings.llm_translit_enabled, state.settings.local_only = True, False
            state.settings.translit_strategy = "api_first"
        state.warmer.notify(invalidate=True)
    return {"connected": True, "languages": state.languages.catalog()}


class ColabUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    colab_url: str = Field(min_length=1, max_length=2048)
    colab_api_key: SecretStr | None = None


@router.post("/admin/colab-url")
async def update_colab(body: ColabUpdate, request: Request):
    state = request.app.state
    state.access.patient(request)
    try:
        url = validate_colab_url(body.colab_url, state.settings.allow_insecure_colab)
        if not url:
            raise ValueError()
    except ValueError:
        raise ServiceError(422, "Provide a valid HTTPS Colab origin without path or credentials") from None
    supplied_key = body.colab_api_key.get_secret_value() if body.colab_api_key is not None else None
    if supplied_key is not None and (not supplied_key or not supplied_key.isascii() or any(c.isspace() for c in supplied_key)):
        raise ServiceError(422, "API key must be nonempty ASCII without whitespace")
    async with state.data_lock:
        state.access.patient(request)
        key = state.gpu.key if supplied_key is None else supplied_key
        encrypted = state.cipher.encrypt(json.dumps({"url": url, "key": key}).encode())
        with state.db.session.begin() as session:
            session.merge(RuntimeSetting(key="colab", value=encrypted))
        state.gpu.configure(url, key)
        state.warmer.notify(invalidate=True)
    return {"colab_url": url, "updated": True}
