import asyncio
import base64
import json

import httpx

from .errors import ServiceError

UNREACHABLE = "Colab server unreachable, restart the notebook and update the URL"


class GPUClient:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.url = settings.colab_url
        self.key = settings.colab_api_key.get_secret_value()
        self.client = client or httpx.AsyncClient(follow_redirects=False, trust_env=False)
        self.semaphore = asyncio.Semaphore(settings.gpu_concurrency)

    def configure(self, url, key=None):
        self.url = url
        if key is not None:
            self.key = key

    async def close(self):
        await self.client.aclose()

    async def request(self, method, path, *, health=False, **kwargs):
        # Snapshot URL AND key so an admin update cannot mix sessions within retries.
        url, key = self.url, self.key
        if not url:
            raise ServiceError(503, UNREACHABLE)
        timeout = self.settings.health_timeout_seconds if health else self.settings.gpu_timeout_seconds
        attempts = 1 if health else self.settings.gpu_retries + 1
        for attempt in range(attempts):
            try:
                async with self.client.stream(method, url + path, headers={"x-api-key": key},
                                              timeout=timeout, **kwargs) as response:
                    if response.status_code in {401, 403}:
                        raise ServiceError(502, "Colab rejected the API key; update COLAB_API_KEY")
                    if response.status_code in {404, 410, 429} or response.status_code >= 500:
                        raise httpx.ConnectError("Temporary upstream error")
                    if response.status_code != 200:
                        raise ServiceError(502, "Colab rejected the request; check model compatibility and request limits")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > self.settings.max_response_bytes:
                            raise ServiceError(502, "Colab response exceeds configured size limit")
                        data.extend(chunk)
                    try:
                        result = json.loads(data)
                        if not isinstance(result, dict):
                            raise ValueError()
                        return result
                    except (ValueError, UnicodeError):
                        raise ServiceError(502, "Colab returned an invalid response") from None
            except httpx.HTTPError:
                if attempt + 1 == attempts:
                    raise ServiceError(503, UNREACHABLE) from None
                await asyncio.sleep(self.settings.retry_backoff_seconds * 2 ** attempt)

    async def health(self):
        data = await self.request("GET", "/health", health=True)
        if data.get("ok") is not True or data.get("lang") != self.settings.lang_tag:
            raise ServiceError(503, "Colab language/model configuration does not match the local backend")
        return {k: data.get(k) for k in ("ok", "gpu", "lang", "languages")}

    async def latents(self, wav):
        async with self.semaphore:
            result = await self.request("POST", "/latents", files={"file": ("reference.wav", wav, "audio/wav")})
        from .voice_store import validate_latents
        validate_latents(result)
        return {k: result[k] for k in ("gpt_cond_latent", "speaker_embedding")}

    async def synthesize(self, text, latents, speed, temperature=None, language=None):
        async with self.semaphore:
            result = await self.request("POST", "/synthesize", json={
                "text": text, **latents, "speed": speed,
                "temperature": self.settings.default_temperature if temperature is None else temperature,
                "language": self.settings.lang_tag if language is None else language,
            })
        try:
            wav = base64.b64decode(result["wav_b64"], validate=True)
            sr = result["sr"]
            if not isinstance(sr, int) or not 8000 <= sr <= 192000:
                raise ValueError()
            return wav, sr
        except (KeyError, ValueError, TypeError):
            raise ServiceError(502, "Colab returned invalid audio") from None
