from fastapi import APIRouter, Request

from ..services.errors import ServiceError
from ..services.languages import LABELS

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    state = request.app.state
    try:
        remote = await state.gpu.health()
        state.languages.update(remote)
        upstream = {"reachable": True, **remote}
    except ServiceError as error:
        upstream = {"reachable": False, "detail": error.detail}
    return {"ok": True, "colab": upstream, "model_version": state.settings.model_version,
            "local_only": state.settings.local_only, "security_mode": state.settings.security_mode,
            "watermark_enabled": state.settings.watermark_enabled,
            "watermark_available": state.watermarker.available,
            "emotion_enabled": state.settings.emotion_enabled,
            "languages": state.languages.catalog(),
            "preview_languages": [{"code": code, "name": name} for code, name in LABELS.items()],
            "reference_limits": {"max_source_seconds": state.settings.max_source_seconds,
                "max_upload_bytes": state.settings.max_upload_bytes, "window_seconds": state.settings.max_reference_seconds},
            "transliteration": {"api_enabled": bool(state.settings.llm_translit_enabled and
                not state.settings.local_only and state.settings.groq_api_key.get_secret_value()),
                "strategy": state.settings.translit_strategy}}


@router.get("/languages")
async def languages(request: Request):
    state = request.app.state
    try:
        state.languages.update(await state.gpu.health())
    except ServiceError:
        pass
    return state.languages.catalog()
