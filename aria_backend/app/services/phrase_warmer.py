"""One background warmer; GPU work never holds the data lock, and stale writes are rejected."""
import asyncio
import logging

from .errors import ServiceError
from .synthesis import render
from .languages import preserve_text

log = logging.getLogger("aria.backend")


class PhraseWarmer:
    def __init__(self, state):
        self.state = state
        self.task = None
        self.epoch = 0
        self.preferred = None
        self.closed = False
        self.event = asyncio.Event()
        self.status = "idle"

    def notify(self, voice_id=None, invalidate=False):
        if voice_id and voice_id != self.preferred:
            self.preferred = voice_id
            self.epoch += 1
        if invalidate:
            self.epoch += 1
        self.event.set()

    def start(self):
        if self.state.settings.phrase_prewarm_enabled:
            self.task = asyncio.create_task(self.run())
            self.notify()
        else:
            self.status = "disabled"

    async def close(self):
        self.closed = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def warm_once(self):
        state = self.state
        async with state.data_lock:
            voices = [p["id"] for p in state.voices.list() if not p["needs_reenrollment"] and
                p.get("available", True) and (state.settings.workflow_mode == "research" or p.get("authorization_status") in {"active", "builtin"})]
            if self.preferred in voices:
                voices.remove(self.preferred)
                voices.insert(0, self.preferred)
            phrases = state.phrases.all()
            phrases.sort(key=lambda p: (not p["favorite"], p["id"]))
            pass_epoch = self.epoch
        for voice_id in voices:
            async with state.data_lock:
                cached_keys = state.phrases.cached_keys(voice_id)
            for snapshot in phrases:
                if pass_epoch != self.epoch:
                    return
                if state.phrases.key(snapshot, voice_id, state.settings.default_speed) in cached_keys:
                    continue
                async with state.data_lock:
                    epoch = self.epoch
                    try:
                        phrase = state.phrases.get(snapshot["id"])
                        _, latents = await state.voices.resolve(voice_id)
                    except ServiceError:
                        continue
                    speed = state.settings.default_speed
                    key = state.phrases.key(phrase, voice_id, speed)
                    if state.phrases.has_audio(key):
                        continue
                self.status = "warming"
                # A foreground cache hit and prediction can run while this awaits the GPU.
                audio = await render(state, preserve_text(phrase["urdu"]), latents, speed, voice_id)
                audio, _ = await state.watermarker.finalize(audio)
                async with state.data_lock:
                    if epoch != self.epoch:
                        return
                    try:
                        current = state.phrases.get(phrase["id"])
                        if voice_id != "aria_builtin":
                            state.voices.get(voice_id)
                    except ServiceError:
                        continue
                    if state.phrases.key(current, voice_id, speed) == key:
                        state.phrases.put_audio(current, voice_id, speed, audio)
                # Yield between phrases so interactive tasks get a turn before the next GPU call.
                await asyncio.sleep(0)
        self.status = "ready"

    async def run(self):
        while not self.closed:
            try:
                await asyncio.wait_for(self.event.wait(), timeout=self.state.settings.phrase_warm_retry_seconds)
            except asyncio.TimeoutError:
                pass
            self.event.clear()
            try:
                await self.warm_once()
            except asyncio.CancelledError:
                raise
            except ServiceError:
                self.status = "waiting_for_gpu"
            except Exception:
                self.status = "error"
                log.warning('{"event":"phrase_warm_failed"}')
