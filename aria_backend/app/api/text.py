from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from ..services.errors import ServiceError
from ..services.languages import LABELS

router = APIRouter()


class TextInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=10000)


class ConversionInput(TextInput):
    language: str = Field("ur", min_length=2, max_length=16, pattern=r"^[a-z]+(?:-[a-z]+)?$")
    input_mode: Literal["auto", "roman", "urdu", "native"] = "auto"


def validate_text(text, settings):
    if not text.strip() or len(text) > settings.max_text_chars:
        raise ServiceError(422, "Enter nonempty text within MAX_TEXT_CHARS")


@router.post("/transliterate")
async def transliterate(body: ConversionInput, request: Request):
    state = request.app.state
    validate_text(body.text, state.settings)
    async with state.data_lock:
        # Text preview is a local/Groq operation and must work when the GPU is offline.
        # Speech endpoints still validate the checkpoint's actual language support.
        if body.language not in LABELS and body.language not in state.languages.mapping():
            raise ServiceError(422, "Unknown preview language")
        return await state.transliterator.convert_language(body.text, body.language, body.input_mode)
