from fastapi import APIRouter, Request
from starlette.datastructures import UploadFile
import hashlib

from ..services.errors import ServiceError

router = APIRouter()


@router.post("/voices", status_code=201)
async def enroll(request: Request):
    state = request.app.state
    actor = state.access.actor(request, "enroll")
    async with request.form(max_files=1, max_fields=2, max_part_size=4096) as form:
        upload, name = form.get("file"), form.get("name")
        if not isinstance(upload, UploadFile) or not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ServiceError(422, "Send one audio file and a voice name of 1–80 characters")
        raw = await upload.read(state.settings.max_upload_bytes + 1)
        if len(raw) > state.settings.max_upload_bytes:
            raise ServiceError(413, "Reference audio is too large")
        async with state.data_lock:
            actor = state.access.actor(request, "enroll")
            provenance = None
            if state.settings.workflow_mode == "assistive":
                identifier = form.get("authorization_id", "")
                if not isinstance(identifier, str):
                    raise ServiceError(422, "Provide a patient authorization identifier")
                provenance = state.access.approval(identifier, hashlib.sha256(raw).hexdigest())
                provenance = {**provenance, "authorization_id": identifier, "enrolling_actor": actor["id"]}
            result = await state.voices.enroll(raw, name.strip(), provenance)
            state.warmer.notify(result["id"])
            return result


@router.get("/voices")
async def list_voices(request: Request):
    async with request.app.state.data_lock:
        try:
            actor = request.app.state.access.actor(request, None)
            if actor["role"] != "patient" and not actor["permissions"]:
                return [request.app.state.builtin.profile()]
        except ServiceError:
            return [request.app.state.builtin.profile()]
        return request.app.state.voices.list()


# Register /all before /{voice_id}; otherwise 'all' would be treated as a voice ID.
@router.delete("/voices/all")
async def delete_all(request: Request):
    async with request.app.state.data_lock:
        state = request.app.state
        state.access.patient(request)
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
        state.access.actor(request, "manage")
        state.voices.delete(voice_id)
        state.liveness.revoke(voice_id)
        await state.predictor.rebuild()
        state.warmer.notify(invalidate=True)


@router.post("/voices/{voice_id}/revoke", status_code=204)
async def revoke_voice(voice_id: str, request: Request):
    state = request.app.state
    async with state.data_lock:
        state.access.patient(request)
        state.voices.revoke(voice_id)
        state.warmer.notify(invalidate=True)
