from fastapi import APIRouter, Request
from starlette.datastructures import UploadFile

from ..services.errors import ServiceError

router = APIRouter()


@router.post("/voices", status_code=201)
async def enroll(request: Request):
    state = request.app.state
    async with request.form(max_files=1, max_fields=1, max_part_size=4096) as form:
        upload, name = form.get("file"), form.get("name")
        if not isinstance(upload, UploadFile) or not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ServiceError(422, "Send one audio file and a voice name of 1–80 characters")
        raw = await upload.read(state.settings.max_upload_bytes + 1)
        if len(raw) > state.settings.max_upload_bytes:
            raise ServiceError(413, "Reference audio is too large")
        async with state.data_lock:
            result = await state.voices.enroll(raw, name.strip())
            state.warmer.notify(result["id"])
            return result


@router.get("/voices")
async def list_voices(request: Request):
    async with request.app.state.data_lock:
        return request.app.state.voices.list()


# Register /all before /{voice_id}; otherwise 'all' would be treated as a voice ID.
@router.delete("/voices/all")
async def delete_all(request: Request):
    async with request.app.state.data_lock:
        state = request.app.state
        state.phrase_translator.invalidate()
        state.voices.delete_all()
        state.liveness.revoke()
        state.phrases.reset()
        await state.predictor.rebuild()
        state.warmer.notify(invalidate=True)
    return {"deleted": "all", "detail": "Personal voice/text data deleted; phrase bank reset to defaults"}


@router.delete("/voices/{voice_id}", status_code=204)
async def delete_voice(voice_id: str, request: Request):
    async with request.app.state.data_lock:
        state = request.app.state
        state.voices.delete(voice_id)
        state.liveness.revoke(voice_id)
        await state.predictor.rebuild()
        state.warmer.notify(invalidate=True)
