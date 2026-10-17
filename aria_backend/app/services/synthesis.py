import asyncio

import anyio

from .audio_utils import stitch_audio
from .chunker import chunk_text


async def render(state, urdu, latents, speed, voice_id=None, language="ur"):
    tag = await state.languages.resolve(language, state.gpu)
    temperature = None
    if state.settings.emotion_enabled and voice_id:
        latents, speed, temperature, _, _ = state.emotions.select(voice_id, urdu, latents, speed)
    chunks = chunk_text(urdu, state.settings.chunk_max_chars, language=language)
    jobs = [asyncio.create_task(state.gpu.synthesize(chunk, latents, speed, temperature=temperature, language=tag)
            if temperature is not None else state.gpu.synthesize(chunk, latents, speed, language=tag)) for chunk in chunks]
    try:
        rendered = await asyncio.gather(*jobs)
    except BaseException:
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        raise
    return await anyio.to_thread.run_sync(stitch_audio, rendered, state.settings)
