"""A.R.I.A. Single-file Flet 0.28.3 app; talks only to the local backend."""
import asyncio
import base64
from dataclasses import dataclass, field, replace
import io
import logging
import math
import os
import re
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit
import wave
import hashlib

import flet as ft
import flet_audio as fta
from flet_audio.audio import ReleaseMode
import httpx

ROOT = Path(__file__).resolve().parent
ASSETS = Path(os.environ.get("FLET_ASSETS_DIR", str(ROOT / "assets")))
BG, PANEL, INK = ft.Colors.SURFACE, ft.Colors.INVERSE_SURFACE, ft.Colors.ON_SURFACE
MUTED, TEAL, RED = ft.Colors.ON_SURFACE_VARIANT, ft.Colors.PRIMARY, ft.Colors.ERROR
SOFT, BORDER, TINT = ft.Colors.SECONDARY_CONTAINER, ft.Colors.OUTLINE_VARIANT, ft.Colors.PRIMARY_CONTAINER


from aria_theme import app_theme, card, clean_field, primary_style, status_pill


def brand(size):
    return ft.Image(src="branding/aria-logo_new.png", width=size, height=size,
        fit=ft.ImageFit.CONTAIN, semantics_label="ARIA logo")


def backend_origin(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    try:
        parsed.port
    except ValueError:
        raise ValueError("The backend port is invalid.") from None
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.path
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or any(c.isspace() for c in value)):
        raise ValueError("Enter an HTTP or HTTPS backend address, such as http://192.168.1.10:8001.")
    return value


def validate_key(value: str) -> str:
    if not value.isascii() or any(c.isspace() for c in value):
        raise ValueError("The key must not contain spaces or non-ASCII characters.")
    return value


def parse_colab_outputs(url_output, key_output):
    urls = re.findall(r"https://[^\s\"'<>]+", url_output or "")
    if len(set(urls)) != 1:
        raise ValueError("Paste the single COLAB_URL line from cell 6.")
    url = backend_origin(urls[0])
    key = (key_output or "").strip()
    if "COLAB_API_KEY" in key or key.startswith("API_KEY"):
        key = re.split(r"[:=]", key, maxsplit=1)[-1].strip()
    key = key.strip("\"'")
    if not key or len(key) > 512:
        raise ValueError("Paste the key shown by cell 3, including its label if you like.")
    return url, validate_key(key)


@dataclass(frozen=True)
class AppSettings:
    backend_url: str = "http://127.0.0.1:8001"
    api_key: str = field(default="", repr=False)
    preview_delay_ms: int = 450
    request_timeout: float = 300
    connect_timeout: float = 5
    max_text_chars: int = 2000
    max_upload_bytes: int = 256 * 1024 * 1024
    max_audio_bytes: int = 32 * 1024 * 1024
    default_speed: float = 1.0
    audio_load_timeout: float = 20
    predict_delay_ms: int = 120
    phrase_refresh_seconds: float = 10

    @classmethod
    def from_env(cls):
        private = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")) / "ARIA/config/desktop.env"
        source = Path(os.environ["ARIA_APP_ENV_FILE"]) if os.environ.get("ARIA_APP_ENV_FILE") else private if private.is_file() else ROOT / ".env"
        # Parse without copying secrets into the process-wide environment.
        from dotenv import dotenv_values
        values = {**dotenv_values(source), **os.environ}
        def number(name, default, cast=float):
            try:
                result = cast(values.get(name, str(default)))
                if not math.isfinite(result) or result <= 0:
                    raise ValueError()
                return result
            except (ValueError, TypeError):
                raise ValueError(f"Check {name}; it must be a positive number.") from None
        result = cls(
            backend_url=backend_origin(values.get("ARIA_BACKEND_URL") or cls.backend_url),
            api_key=validate_key(values.get("ARIA_KEY") or ""),
            preview_delay_ms=number("ARIA_PREVIEW_DELAY_MS", 450, int),
            request_timeout=number("ARIA_REQUEST_TIMEOUT_SECONDS", 300),
            connect_timeout=number("ARIA_CONNECT_TIMEOUT_SECONDS", 5),
            max_text_chars=number("ARIA_MAX_TEXT_CHARS", 2000, int),
            max_upload_bytes=number("ARIA_MAX_UPLOAD_BYTES", 268435456, int),
            max_audio_bytes=number("ARIA_MAX_AUDIO_BYTES", 33554432, int),
            default_speed=number("ARIA_DEFAULT_SPEED", 1.0),
            audio_load_timeout=number("ARIA_AUDIO_LOAD_TIMEOUT_SECONDS", 20),
            predict_delay_ms=number("ARIA_PREDICT_DELAY_MS", 120, int),
            phrase_refresh_seconds=number("ARIA_PHRASE_REFRESH_SECONDS", 10),
        )
        if not 0.5 <= result.default_speed <= 2:
            raise ValueError("ARIA_DEFAULT_SPEED must be between 0.5 and 2.0.")
        return result


class AppError(Exception):
    """Only locally written, safe-to-display error messages belong in this exception."""


def response_error(status: int, operation: str) -> str:
    if operation in {"account", "authorize"}:
        if status == 401:
            return "Unlock the local account with the correct account ID and PIN."
        if status == 403:
            return "This account is not authorized for that action. Caregiver access does not establish patient consent."
        if status == 429:
            return "Too many attempts. Wait before trying your PIN again."
        if status == 409:
            return "Check whether a patient PIN is already configured before repeating setup."
    if status == 401:
        return "Unlock your local account, or check the backend key in Advanced settings."
    if status == 403:
        if operation == "emotion":
            return "Use a recording of the selected speaker, and renew voice verification if it expired."
        return ("That recording did not match the phrase or speaker. Request a new challenge and try again."
                if operation == "verify" else "Verify the selected voice before speaking or changing its references.")
    if status == 410:
        return "This challenge expired or was already used. Request a new one."
    if status == 404 and operation == "speak":
        return "That voice or phrase is no longer available. Refresh and try again."
    if status == 409:
        if operation == "phrases":
            return "Your phrases changed. Refresh to load the current translations."
        if operation == "challenge":
            return "Re-enroll this voice with verification enabled in the backend before requesting a challenge."
        if operation == "phrase-edit":
            return "The phrase bank is full. Delete a phrase before adding another."
        return "This voice needs a new recording after the model changed. Enroll it again."
    if status == 413:
        return "That recording or message is too large. Choose a shorter one."
    if status == 422:
        if operation == "phrase-edit":
            return "Enter Roman Urdu and Urdu-script text, up to 180 characters each, and choose a category."
        return ("No suitable reference section was found, or the recording exceeds the backend limits. Use clear single-speaker audio."
                if operation == "enroll" else "Check your message and speed. Try a shorter sentence.")
    if status == 429:
        return "The server is busy. Please wait a moment and try again."
    if status == 503:
        if operation == "phrases":
            return "Phrase translation is unavailable. Add or check your Groq key in Connect, then refresh."
        if operation == "preview":
            return "Automatic conversion is unavailable. Check your Groq key or choose Native script to use your text as written."
        if operation in {"verify", "challenge"}:
            return "Voice checking is unavailable. Check the backend's local verification models."
        return "Speech is unavailable. Check Colab, the selected voice assets, and required AudioSeal protection. Your text is preserved."
    if status == 502:
        return "The backend could not use the voice server. Check its Colab connection and key."
    return "The request could not finish. Check the backend and try again."


def valid_wav(raw: bytes) -> bool:
    try:
        with wave.open(io.BytesIO(raw), "rb") as audio:
            frames = audio.getnframes()
            expected = frames * audio.getnchannels() * audio.getsampwidth()
            return (audio.getnchannels() == 1 and audio.getsampwidth() == 2 and
                    8000 <= audio.getframerate() <= 192000 and frames > 0 and
                    expected <= len(raw) and len(audio.readframes(frames)) == expected)
    except (wave.Error, EOFError, ValueError):
        return False


class BackendClient:
    def __init__(self, settings: AppSettings, transport=None):
        self.settings = settings
        self.sessions = {}
        self.watermark_policy = "required"
        self.last_expression = {}
        headers = {"Authorization": "Bearer " + settings.api_key} if settings.api_key else {}
        self.http = httpx.AsyncClient(base_url=settings.backend_url, headers=headers,
            timeout=httpx.Timeout(settings.request_timeout, connect=settings.connect_timeout),
            follow_redirects=False, trust_env=False, transport=transport)

    async def close(self):
        self.sessions.clear()
        self.http.headers.pop("X-ARIA-Account", None)
        await self.http.aclose()

    def session_valid(self, voice_id):
        session = self.sessions.get(voice_id)
        return bool(session and session["expires"] > time.monotonic())

    def session_headers(self, voice_id):
        return {"X-ARIA-Session": self.sessions[voice_id]["token"]} if self.session_valid(voice_id) else {}

    async def request(self, method, path, operation, **kwargs):
        if self.http.is_closed:
            raise AppError("The connection was closed. Reconnect in Connection settings.")
        try:
            # No automatic retries: a repeated speak/enrollment could duplicate remote work.
            async with self.http.stream(method, path, **kwargs) as response:
                if response.status_code not in {200, 201, 202, 204}:
                    if response.status_code == 403:
                        self.sessions.clear()
                    raise AppError(response_error(response.status_code, operation))
                limit = self.settings.max_audio_bytes if operation == "speak" else 1024 * 1024
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > limit:
                        raise AppError("The response was too large. Try a shorter message.")
                    data.extend(chunk)
                return httpx.Response(response.status_code, headers=response.headers, content=bytes(data))
        except httpx.TimeoutException:
            raise AppError("The request took too long. Wait a moment before trying again; Colab may still be working.") from None
        except httpx.HTTPError:
            raise AppError("Cannot reach the backend. Check Connection settings and make sure it is running.") from None

    async def json_request(self, method, path, operation, **kwargs):
        response = await self.request(method, path, operation, **kwargs)
        try:
            return response.json()
        except ValueError:
            raise AppError("The backend returned an unreadable response. Check its address.") from None

    async def voices(self):
        data = await self.json_request("GET", "/api/voices", "voices")
        if not isinstance(data, list) or any(not isinstance(v, dict) or
            not isinstance(v.get("id"), str) or not isinstance(v.get("name"), str) for v in data):
            raise AppError("The voice list could not be read. Refresh and try again.")
        return data

    async def health(self):
        data = await self.json_request("GET", "/api/health", "health",
            timeout=httpx.Timeout(10, connect=self.settings.connect_timeout))
        if not isinstance(data, dict) or not isinstance(data.get("colab"), dict):
            raise AppError("The backend status could not be read.")
        self.watermark_policy = ("research_unprotected" if data.get("workflow_mode") == "research" and
            data.get("watermark_policy") == "research_unprotected" else "required")
        return data

    def check_protection(self, response):
        status = response.headers.get("x-aria-watermark")
        if self.watermark_policy == "required" and (status != "verified" or response.headers.get("x-aria-watermark-policy") != "required"):
            raise AppError("Playback withheld: the server did not confirm required audio protection. Update the backend and AudioSeal setup.")
        self.last_expression = {"requested": response.headers.get("x-aria-emotion-requested", "neutral"),
            "effective": response.headers.get("x-aria-emotion", "neutral"),
            "method": response.headers.get("x-aria-emotion-method", "neutral")}

    async def preview(self, text, language="ur", mode="auto"):
        data = await self.json_request("POST", "/api/transliterate", "preview",
            json={"text": text, "language": language, "input_mode": mode})
        value = data.get("text", data.get("urdu")) if isinstance(data, dict) else None
        if not isinstance(value, str):
            raise AppError("The language preview could not be read.")
        return value

    async def connect_colab(self, url, key, groq=""):
        codes = {
            "invalid_connection": "Check the Colab URL and key. Paste the outputs from cells 6 and 3.",
            "notebook_update_required": "Upload the updated ARIA notebook and run cells 3–6, then paste the new outputs.",
            "colab_key_rejected": "Colab rejected this key. Use the key from cell 3 in the same running notebook as the URL.",
            "colab_response_invalid": "That server did not return a valid ARIA response. Use the URL from cell 6 of the updated notebook.",
            "model_mismatch": "The model language configuration differs from this installation. Check LANG_TAG in Colab and the backend.",
            "colab_unreachable": "This Colab URL is offline. Keep cell 6 running and paste its latest URL.",
        }
        try:
            async with self.http.stream("POST", "/api/admin/connect", json={"colab_url": url,
                "colab_api_key": key, "groq_api_key": groq or None}, timeout=20) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > 65536:
                        raise AppError("The connection response was invalid.")
                    raw.extend(chunk)
                import json
                try:
                    data = json.loads(raw)
                except ValueError:
                    raise AppError("The connection response was invalid.") from None
                if not isinstance(data, dict):
                    raise AppError("The connection response was invalid.")
                if response.status_code != 200:
                    raise AppError(codes.get(data.get("code"), response_error(response.status_code, "connect")))
                if data.get("connected") is not True:
                    raise AppError("Connection could not be confirmed.")
                return data
        except httpx.HTTPError:
            raise AppError("The local server is not responding. Close the app and double-click Start ARIA.bat.") from None

    async def speak(self, text, voice_id, speed, mode, language="ur", emotion="neutral"):
        response = await self.request("POST", "/api/tts", "speak",
            headers=self.session_headers(voice_id),
            json={"text": text, "voice_id": voice_id, "speed": speed, "input_mode": mode, "language": language, "emotion": emotion})
        if response.headers.get("content-type", "").split(";")[0] != "audio/wav" or not valid_wav(response.content):
            raise AppError("The backend did not return a playable WAV. Try again or check the model.")
        self.check_protection(response)
        return response.content, unquote(response.headers.get("x-spoken-text", response.headers.get("x-urdu-text", "")))

    async def enroll(self, path: Path, name: str, authorization_id=None):
        raw = await self.read_reference(path)
        data = await self.json_request("POST", "/api/voices", "enroll",
            files={"file": ("reference" + path.suffix.lower(), raw, "application/octet-stream")},
            data={"name": name, **({"authorization_id": authorization_id} if authorization_id else {})})
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise AppError("Enrollment could not be confirmed. Refresh the voice list before trying again.")
        return data["id"]

    async def authorize_recording(self, path, source_type, basis, reference):
        raw = await self.read_reference(path)
        result = await self.json_request("POST", "/api/access/authorizations", "authorize",
            json={"recording_sha256": hashlib.sha256(raw).hexdigest(), "source_type": source_type,
                "basis": basis, "authorization_reference": reference})
        return result["authorization_id"]

    async def account(self, action="status", **values):
        result = await self.json_request("GET" if action in {"status", "caregivers"} and not values else "POST",
            "/api/access/" + action, "account", **({"json": values} if values else {}))
        if isinstance(result, dict) and result.get("account_token"):
            self.http.headers["X-ARIA-Account"] = result["account_token"]
        if action == "logout":
            self.http.headers.pop("X-ARIA-Account", None)
        return result

    async def revoke_caregiver(self, actor_id):
        await self.request("DELETE", "/api/access/caregivers/" + quote_id(actor_id), "account")

    async def read_reference(self, path, wav_only=False):
        def read_reference():
            try:
                with path.open("rb") as source:
                    raw = source.read(self.settings.max_upload_bytes + 1)
            except OSError:
                raise AppError("That file cannot be opened. Select audio stored on this device.") from None
            if len(raw) > self.settings.max_upload_bytes:
                raise AppError("That recording is too large. Choose a shorter file.")
            if wav_only and (len(raw) < 12 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE"):
                raise AppError("Voice verification requires a WAV recording.")
            if not raw:
                raise AppError("That audio file is empty.")
            return raw
        return await asyncio.to_thread(read_reference)

    async def challenge(self, voice_id):
        data = await self.json_request("POST", "/api/liveness/challenge", "challenge", json={"voice_id": voice_id})
        if not isinstance(data, dict) or not all(isinstance(data.get(k), str) for k in ("challenge_id", "voice_id", "phrase")):
            raise AppError("The challenge could not be read.")
        return data

    async def verify(self, identifier, path):
        raw = await self.read_reference(path, wav_only=True)
        data = await self.json_request("POST", "/api/liveness/verify", "verify",
            files={"file": ("challenge.wav", raw, "audio/wav")}, data={"challenge_id": identifier})
        if (not isinstance(data, dict) or data.get("verified") is not True or
                not isinstance(data.get("session_token"), str) or not isinstance(data.get("voice_id"), str)
                or not isinstance(data.get("expires_in"), (int, float))):
            raise AppError("Verification could not be confirmed. Request a new challenge.")
        self.sessions[data["voice_id"]] = {"token": data["session_token"], "expires": time.monotonic() + data["expires_in"]}
        return data["expires_in"]

    async def add_emotion(self, voice_id, emotion, path, authorization_id=None):
        raw = await self.read_reference(path)
        return await self.json_request("POST", "/api/voices/" + quote_id(voice_id) + "/emotions/" + emotion, "emotion",
            headers=self.session_headers(voice_id), files={"file": ("reference" + path.suffix.lower(), raw, "application/octet-stream")},
            data={"authorization_id": authorization_id} if authorization_id else {})

    async def phrases(self, voice_id, speed, language="ur", emotion="neutral"):
        data = await self.json_request("GET", "/api/phrases", "phrases",
            params={"voice_id": voice_id or "default", "speed": speed, "language": language, "emotion": emotion})
        if not isinstance(data, dict) or not isinstance(data.get("items"), list) or any(
            not isinstance(item, dict) or any(not isinstance(item.get(k), str) for k in ("id", "roman", "urdu", "category"))
            for item in data["items"]):
            raise AppError("The phrase bank could not be read. Check that the backend includes Phase 4.")
        if language != "ur" and (data.get("language") != language or any(
                item.get("language") != language or not isinstance(item.get("display_text"), str) for item in data["items"])):
            raise AppError("Restart the local server to load quick phrases in your selected language.")
        return data

    async def warm_phrases(self, voice_id):
        return await self.json_request("POST", "/api/phrases/warm", "phrases", json={"voice_id": voice_id})

    async def predict(self, prefix):
        data = await self.json_request("GET", "/api/predict", "predict", params={"prefix": prefix})
        if not isinstance(data, dict) or not isinstance(data.get("suggestions"), list) or any(
            not isinstance(word, str) for word in data["suggestions"]):
            raise AppError("Suggestions are unavailable.")
        return data["suggestions"][:5]

    async def save_phrase(self, identifier, values):
        path = "/api/phrases" + ("/" + quote_id(identifier) if identifier else "")
        return await self.json_request("PATCH" if identifier else "POST", path, "phrase-edit", json=values)

    async def delete_phrase(self, identifier):
        await self.request("DELETE", "/api/phrases/" + quote_id(identifier), "phrase-edit")

    async def speak_phrase(self, identifier, voice_id, speed, language="ur", emotion="neutral"):
        response = await self.request("POST", "/api/phrases/" + quote_id(identifier) + "/speak", "speak",
            headers=self.session_headers(voice_id),
            json={"voice_id": voice_id, "speed": speed, "language": language, "emotion": emotion})
        if response.headers.get("content-type", "").split(";")[0] != "audio/wav" or not valid_wav(response.content):
            raise AppError("The phrase audio could not be played. Try again.")
        self.check_protection(response)
        return response.content, unquote(response.headers.get("x-spoken-text", response.headers.get("x-urdu-text", "")))


def quote_id(identifier):
    from urllib.parse import quote
    return quote(identifier, safe="")


def insert_suggestion(text, word):
    # Prefix predictions describe the text end. Replace only its unfinished Roman token.
    match = re.search(r"[a-z0-9']+$", text, re.I)
    return (text[:match.start()] if match else text + ("" if not text or text[-1].isspace() else " ")) + word + " "


class AriaApp:
    def __init__(self, page, settings, client=None):
        self.page, self.settings = page, settings
        self.client = client or BackendClient(settings)
        self.busy = False
        self.closed = False
        self.revision = 0
        self.preview_task = None
        self.preview_request_key = None
        self.preview_phase = None
        self.native_override = False
        self.predict_task = None
        self.phrase_poll_task = None
        self.phrase_revision = 0
        self.phrase_signature = None
        self.phrase_language = None
        self.phrase_loading = False
        self.phrases = []
        self.phrase_controls = []
        self.audio_watch = None
        self.audio = None
        self.audio_loaded = False
        self.voices = []
        self.selected_file = None
        self.dialog = None
        self.dialog_kind = None
        self.security_mode = "off"
        self.emotion_enabled = False
        self.workflow_mode = "assistive"
        self.access_state = {"actor": None, "pin_configured": False}
        self.language_names = {"en": "English", "ur": "Urdu"}
        self.api_translit_enabled = False
        self.server_ready = False
        self.backend_ready = False
        self.status_error = False
        self.screen = "welcome"
        self.onboarding_active = True
        self.reference_limits = {"max_source_seconds": 1800, "max_upload_bytes": self.settings.max_upload_bytes, "window_seconds": 30}
        self.build()

    def build(self):
        page = self.page
        page.title = "A.R.I.A · Your voice"
        page.theme_mode = ft.ThemeMode.LIGHT
        page.theme, page.dark_theme = app_theme(), app_theme(dark=True)
        page.bgcolor, page.padding = BG, 12
        page.scroll = None
        page.window.width, page.window.height = 480, 820
        page.window.min_width, page.window.min_height = 340, 560
        mobile = page.platform in {ft.PagePlatform.ANDROID, ft.PagePlatform.IOS}
        has_font = (ASSETS / "fonts" / "NotoNastaliqUrdu.ttf").is_file()
        self.font = "NotoNastaliqUrdu" if has_font or mobile else None
        page.fonts = {"NotoNastaliqUrdu": "fonts/NotoNastaliqUrdu.ttf"} if self.font else {}
        self.status = ft.Text("Connecting…", color=MUTED, size=13, selectable=True)
        self.connection = ft.Text("Connecting", size=11, color=MUTED)
        self.conversion_note = ft.Text("Roman Urdu or Urdu. Your choice.", color=MUTED, size=12)
        self.progress = ft.ProgressBar(visible=False, color=TEAL, height=3, border_radius=3)
        self.input = ft.TextField(hint_text="Write your message…",
            multiline=True, min_lines=2, max_lines=4, max_length=self.settings.max_text_chars,
            text_size=22, border=ft.InputBorder.NONE, border_color=ft.Colors.TRANSPARENT,
            filled=False, content_padding=0, cursor_color=TEAL, counter_text="",
            on_change=self.text_changed, on_blur=self.text_blurred)
        self.mode = ft.Dropdown(label="Input", value="auto", options=[
            ft.dropdown.Option("auto", "Auto-convert"), ft.dropdown.Option("native", "Native script")], on_change=self.mode_changed, width=170,
            filled=True, fill_color=SOFT, border_color=BORDER, border_radius=12, text_size=13)
        self.language = ft.Dropdown(label="Speak in", value="ur", options=[ft.dropdown.Option("ur", "Urdu")],
            on_change=self.language_changed, expand=True, filled=True, fill_color=PANEL, border_color=BORDER,
            border_radius=12, text_size=13)
        self.language_note = ft.Text("Connect the updated Colab notebook to discover other model languages.", size=12, color=MUTED)
        self.source_title = ft.Text("Roman Urdu input", size=12, color=MUTED)
        self.native_count = ft.Text(f"0 / {self.settings.max_text_chars}", size=12, color=MUTED)
        self.preview = ft.TextField(value="", hint_text="Converted Urdu text appears here",
            multiline=True, min_lines=2, max_lines=5, max_length=self.settings.max_text_chars, counter_text="",
            border=ft.InputBorder.NONE, filled=False, content_padding=ft.padding.symmetric(vertical=8),
            text_size=20, color=INK, text_style=ft.TextStyle(font_family=self.font),
            text_align=ft.TextAlign.RIGHT, rtl=True, cursor_color=TEAL, on_change=self.native_changed)
        self.preview_note = ft.Text("A preview of what you’ll say.", size=12, color=MUTED)
        self.voice = ft.Dropdown(label="Selected voice", options=[], expand=True, on_change=self.voice_changed,
            hint_text="No voice yet", filled=True, fill_color=SOFT, border_color=BORDER, border_radius=12, text_size=14)
        self.voice_note = ft.Text("", color=MUTED, size=13)
        self.refresh_button = ft.IconButton(ft.Icons.REFRESH, tooltip="Refresh voices and connection",
            icon_color=TEAL, width=44, height=48, on_click=self.refresh_clicked)
        self.enroll_button = ft.OutlinedButton("Add a voice", icon=ft.Icons.ADD,
            height=48, on_click=self.open_enrollment,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=12), side=ft.BorderSide(1, BORDER)))
        self.verify_button = ft.OutlinedButton("Experimental spoken check", icon=ft.Icons.VERIFIED_USER_OUTLINED,
            height=52, visible=False, on_click=self.open_verification)
        self.emotion_button = ft.OutlinedButton("Emotion reference", height=52, visible=False, on_click=self.open_emotion)
        self.safety_note = ft.Text("", size=13, color=MUTED)
        self.settings_button = ft.IconButton(ft.Icons.SETTINGS_OUTLINED, tooltip="Voice server connection",
            width=44, height=44, icon_color=MUTED, on_click=self.open_connection)
        self.theme_button = ft.IconButton(ft.Icons.DARK_MODE_OUTLINED, tooltip="Switch appearance",
            width=44, height=44, icon_color=MUTED, on_click=self.toggle_theme)
        self.account_button = ft.IconButton(ft.Icons.LOCK_OUTLINE, tooltip="Account and caregiver access", on_click=self.open_account)
        self.expression = ft.Dropdown(label="Expression", value="neutral", expand=True, border_radius=14,
            filled=True, fill_color=PANEL, border_color=BORDER, text_size=14,
            options=[ft.dropdown.Option(code, name) for code, name in [("neutral", "Neutral"), ("happy", "Happy"),
                ("sad", "Sad"), ("angry", "Angry"), ("calm", "Calm"), ("auto", "Suggest from text")]],
            on_change=self.expression_changed)
        self.expression_note = ft.Text("Expression uses available authorized references; audible emotion still needs evaluation.", size=12, color=MUTED)
        self.phrase_expression_note = ft.Text(self.expression_note.value, size=12, color=MUTED)
        self.phrase_expression_label = ft.Text("Expression · Neutral", size=14, color=INK)
        expression_items = []
        for choice in ("neutral", "happy", "sad", "angry", "calm", "auto"):
            async def choose_expression(event, value=choice):
                self.expression.value = value
                await self.expression_changed()
            expression_items.append(ft.PopupMenuItem(text=choice.title(), on_click=choose_expression))
        self.phrase_expression = ft.PopupMenuButton(content=ft.Container(self.phrase_expression_label,
            padding=12, bgcolor=PANEL, border_radius=100), items=expression_items)
        self.protection_note = ft.Text("Required audio protection · unverified output is withheld.", size=12, color=MUTED)
        self.library_protection_note = ft.Text(self.protection_note.value, size=12, color=MUTED)
        self.speed_label = ft.Text(f"Speaking speed · {self.settings.default_speed:.1f}×", color=INK, size=13)
        self.speed = ft.Slider(min=0.5, max=2.0, divisions=15, value=self.settings.default_speed,
            label="{value}×", active_color=TEAL, on_change=self.speed_changed, on_change_end=self.speed_committed)
        self.suggestion_row = ft.Row(wrap=True, spacing=8)
        self.phrase_grid = ft.Column(spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.phrase_status = ft.Text("Loading quick phrases…", size=13, color=MUTED)
        self.phrase_filter = ft.Dropdown(label="Category", value="all", width=195, filled=True,
            fill_color=PANEL, border_color=BORDER, border_radius=12, text_size=14, options=[
            ft.dropdown.Option(value, label) for value, label in [("all", "All phrases"), ("favorites", "Favorites"),
            ("recent", "Recently spoken"), ("needs", "Needs"), ("medical", "Medical"), ("family", "Family"),
            ("greetings", "Greetings"), ("custom", "Custom")]], on_change=self.phrase_filter_changed)
        self.add_phrase_button = ft.OutlinedButton("Add phrase", icon=ft.Icons.ADD, height=52, on_click=self.add_phrase)
        self.phrase_search = ft.TextField(hint_text="Search your phrases", prefix_icon=ft.Icons.SEARCH,
            filled=True, bgcolor=PANEL, border_color=BORDER, border_radius=12, text_size=14,
            on_change=self.phrase_filter_changed, col={"xs": 12, "sm": 6})
        self.speak_button = ft.ElevatedButton("Speak", icon=ft.Icons.VOLUME_UP_ROUNDED,
            height=54, expand=True, on_click=self.speak_clicked, style=primary_style())
        self.stop_button = ft.IconButton(icon=ft.Icons.STOP_ROUNDED, tooltip="Stop", height=54, width=54,
            on_click=self.stop_clicked, disabled=True, icon_color=MUTED, bgcolor=PANEL,
            style=ft.ButtonStyle(shape=ft.CircleBorder(), side=ft.BorderSide(0.5, BORDER)))
        self.picker = ft.FilePicker(on_result=self.file_selected)
        page.overlay.append(self.picker)
        self.preview_title = ft.Text("Urdu preview", size=12, color=TEAL, weight=ft.FontWeight.W_500)
        self.preview_note.visible = False
        self.mode_pill = ft.PopupMenuButton(content=ft.Container(ft.Row([
            ft.Text("Auto-convert", size=12, color=INK), ft.Icon(ft.Icons.EXPAND_MORE, size=16, color=MUTED)], tight=True),
            bgcolor=SOFT, border_radius=100, padding=ft.padding.symmetric(horizontal=12, vertical=8)),
            items=[ft.PopupMenuItem(text="Auto-convert", on_click=self.auto_mode),
                   ft.PopupMenuItem(text="Native script", on_click=self.native_mode)])
        self.char_count = ft.Text(f"0 / {self.settings.max_text_chars}", size=12, color=MUTED)
        panel = ft.Column([ft.Row([self.preview_title, self.native_count],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN), self.preview, self.preview_note], spacing=8)
        composer = card(ft.Column([
            self.source_title, self.input, self.suggestion_row, ft.Divider(color=BORDER, thickness=0.5, height=16), panel,
            ft.Row([self.mode_pill, self.char_count], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        ], spacing=16))
        self.safety_actions = ft.Row([self.verify_button, self.emotion_button], wrap=True, visible=False)
        voice_card = card(ft.Column([
            ft.Text("Choose a saved voice or add a recording.", size=14, color=MUTED),
            ft.Row([self.voice, self.refresh_button], spacing=4), self.voice_note,
            self.enroll_button,
        ], spacing=10))
        self.conversion_note.visible = False
        self.speech_emotion_label = ft.Text("Neutral", size=13, weight=ft.FontWeight.W_500, color=INK)
        self.compose_view = ft.Column([
            ft.Text("What would you like to say?", size=26, color=INK,
                    weight=ft.FontWeight.BOLD),
            ft.Text("Write a message or choose a saved phrase.", size=13, color=MUTED),
            composer,
            ft.Row([
                ft.OutlinedButton("Emotion", icon=ft.Icons.SENTIMENT_SATISFIED_OUTLINED,
                                  on_click=self.open_speech_settings),
                self.speech_emotion_label,
                ft.Container(expand=True),
                ft.IconButton(ft.Icons.COPY_OUTLINED, tooltip="Copy message",
                              on_click=self.copy_message),
            ], spacing=10),
            self.conversion_note,
        ], spacing=14)
        self.library_voice = ft.Text("Choose a voice in Compose to speak phrases.", color=MUTED, size=13)
        self.library_view = ft.Column([
            ft.Text("Quick phrases", size=26, color=INK, weight=ft.FontWeight.W_500),
            self.library_voice, self.phrase_expression, self.phrase_search,
            ft.Row([self.phrase_filter, self.add_phrase_button], wrap=True), self.phrase_status, self.phrase_grid,
        ], spacing=16, visible=False)
        self.navigation = ft.CupertinoSlidingSegmentedButton(selected_index=0, width=260, height=44,
            controls=[ft.Text("Compose", size=14, weight=ft.FontWeight.W_500, color=INK),
                      ft.Text("Phrases", size=14, weight=ft.FontWeight.W_500, color=INK)],
            bgcolor=SOFT, thumb_color=PANEL, padding=4, on_change=self.change_view)
        header = ft.Row([
            ft.Container(brand(48), expand=True, alignment=ft.alignment.center_left),
            self.account_button, self.theme_button, self.settings_button,
        ], spacing=4)
        self.start_button = ft.FilledButton("Get started", icon=ft.Icons.ARROW_FORWARD, height=54, width=300, on_click=self.get_started)
        self.welcome_status = ft.Text("", size=12, color=MUTED, visible=False)
        self.welcome_spacer, self.welcome_logo = ft.Container(height=40), brand(210)
        self.welcome_view = ft.Column([
            ft.Container(height=36), self.welcome_logo,
            ft.Container(height=18),
            ft.Text("Your voice. Your way.", size=30, weight=ft.FontWeight.BOLD,
                    color=INK, text_align=ft.TextAlign.CENTER),
            ft.Text("Communicate naturally, in words that feel like yours.",
                size=15, color=MUTED, text_align=ft.TextAlign.CENTER),
            ft.Container(height=30),
            self.start_button,
            ft.Text("Designed for accessible everyday communication.", size=12,
                    color=MUTED, text_align=ft.TextAlign.CENTER),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=16)
        self.language_setup_view = ft.Column([
            ft.Text("01 / 03  ·  GET STARTED", color=TEAL, size=12, weight=ft.FontWeight.BOLD),
            ft.Container(height=20),
            ft.Icon(ft.Icons.LANGUAGE, size=48, color=TEAL),
            ft.Text("Choose your language", size=28, weight=ft.FontWeight.BOLD, color=INK),
            ft.Text("Start in Urdu or English. You can change this at any time.", color=MUTED, size=14),
            card(ft.Column([
                ft.Text("Preferred speaking language", weight=ft.FontWeight.W_500),
                ft.Row([ft.OutlinedButton("اردو  ·  Urdu", on_click=self.onboarding_urdu),
                        ft.OutlinedButton("English", on_click=self.onboarding_english)], wrap=True),
                ft.Text("Available speech languages depend on your connected model.", size=12, color=MUTED),
            ], spacing=16)),
            ft.Container(height=30),
            ft.FilledButton("Continue", icon=ft.Icons.ARROW_FORWARD, height=54,
                            on_click=self.onboarding_language_continue),
        ], spacing=14, visible=False)
        self.security_setup_view = ft.Column([
            ft.Text("02 / 03  ·  PRIVACY", color=TEAL, size=12, weight=ft.FontWeight.BOLD),
            ft.Container(height=20),
            ft.Icon(ft.Icons.LOCK_OUTLINE, size=48, color=TEAL),
            ft.Text("Your account, your control", size=27, weight=ft.FontWeight.BOLD, color=INK),
            ft.Text("Protect your voice and control who can use it.", color=MUTED, size=14),
            card(ft.Column([
                ft.ListTile(leading=ft.Icon(ft.Icons.PIN_OUTLINED, color=TEAL),
                            title=ft.Text("Speech-free PIN"),
                            subtitle=ft.Text("Unlock without speaking"), on_click=self.open_account),
                ft.Divider(height=4),
                ft.ListTile(leading=ft.Icon(ft.Icons.PEOPLE_OUTLINE, color=TEAL),
                            title=ft.Text("Caregiver permissions"),
                            subtitle=ft.Text("Share only the access you approve"), on_click=self.open_account),
            ], spacing=4), padding=12),
            ft.Text("Consent for recording is collected separately before enrollment.",
                    color=MUTED, size=12),
            ft.Container(height=30),
            ft.FilledButton("Choose a voice", icon=ft.Icons.ARROW_FORWARD, height=54,
                            on_click=self.onboarding_security_continue),
        ], spacing=14, visible=False)
        self.use_aria_button = ft.FilledButton("Use ARIA Voice", icon=ft.Icons.RECORD_VOICE_OVER, height=52, on_click=self.use_aria_voice)
        self.builtin_note = ft.Text("Requires a configured licensed synthetic reference and connected model.", size=12, color=MUTED)
        self.voices_view = ft.Column([
            ft.Text("03 / 03  ·  YOUR VOICE", color=TEAL, size=12, weight=ft.FontWeight.BOLD),
            ft.Text("Choose your voice", size=28, weight=ft.FontWeight.BOLD, color=INK),
            ft.Text("Use a licensed ARIA voice, or bring your own recording.", size=14, color=MUTED),
            card(ft.Column([
                ft.Row([ft.Icon(ft.Icons.AUTO_AWESOME, color=TEAL),
                        ft.Text("ARIA Default Voice", weight=ft.FontWeight.BOLD, size=17)]),
                ft.Text("A synthetic voice with no personal recording required.", color=MUTED, size=13),
                self.use_aria_button,
                self.builtin_note,
            ], spacing=12)),
            card(ft.Column([
                ft.Row([ft.Icon(ft.Icons.RECORD_VOICE_OVER, color=TEAL),
                        ft.Text("My own voice", weight=ft.FontWeight.BOLD, size=17)]),
                ft.Text("Select an authorized saved voice or enroll a recording.", color=MUTED, size=13),
                voice_card,
            ], spacing=12)),
            ft.TextButton("Connect voice server", icon=ft.Icons.LINK,
                          on_click=self.open_connection),
        ], spacing=14, visible=False)
        self.ready_view = ft.Column([
            ft.Container(height=60),
            ft.Icon(ft.Icons.CHECK_CIRCLE_OUTLINE, color=TEAL, size=90),
            ft.Text("You're ready to communicate", size=28, weight=ft.FontWeight.BOLD,
                    text_align=ft.TextAlign.CENTER, color=INK),
            ft.Text("Type freely, use quick phrases, and speak whenever your voice is available.",
                    size=14, color=MUTED, text_align=ft.TextAlign.CENTER),
            ft.Container(height=18),
            ft.FilledButton("Start speaking", icon=ft.Icons.ARROW_FORWARD,
                            height=56, width=270, on_click=self.finish_onboarding),
        ], spacing=18, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
           visible=False)
        self.voice_continue = ft.FilledButton("Continue to speaking", icon=ft.Icons.ARROW_FORWARD,
            height=54, expand=True, on_click=self.continue_speaking)
        self.voice_actions = ft.Row([self.voice_continue], visible=False)
        self.colab_key_field = ft.TextField(label="Key from cell 3", password=True, can_reveal_password=True,
            hint_text="Paste the key or the full key output line", border_radius=12)
        self.colab_url_field = ft.TextField(label="URL from cell 6", hint_text="COLAB_URL=https://…trycloudflare.com",
            multiline=True, min_lines=1, max_lines=3, border_radius=12)
        self.groq_field = ft.TextField(label="Groq API key (optional)", password=True, can_reveal_password=True,
            border_radius=12)
        for field in (self.colab_key_field, self.colab_url_field, self.groq_field):
            clean_field(field)
        self.connect_error = ft.Text("", color=RED, size=12, selectable=True, max_lines=3, overflow=ft.TextOverflow.ELLIPSIS)
        self.connect_button = ft.FilledButton("Check & connect", icon=ft.Icons.LINK, height=54, on_click=self.save_colab)
        self.connect_progress = ft.ProgressRing(width=22, height=22, visible=False)
        self.connection_view = ft.Column([
            ft.Text("Connect your voice", size=28, weight=ft.FontWeight.BOLD),
            ft.Text("Link your running speech model to enable playback.", size=15, color=MUTED),
            card(ft.Column([self.colab_key_field, ft.Divider(height=1), self.colab_url_field,
                ft.Divider(height=1), self.groq_field, self.connect_error], spacing=8), padding=20),
            ft.Row([ft.Container(self.connect_button, expand=True), self.connect_progress]),
            ft.ListTile(title=ft.Text("Use saved voices offline", size=15), trailing=ft.Icon(ft.Icons.CHEVRON_RIGHT, color=MUTED),
                on_click=self.show_voices, shape=ft.RoundedRectangleBorder(radius=14)),
            ft.ListTile(title=ft.Text("Advanced", size=15), trailing=ft.Icon(ft.Icons.CHEVRON_RIGHT, color=MUTED),
                on_click=self.open_settings, shape=ft.RoundedRectangleBorder(radius=14)),
            ft.Text("Groq converts your text when enabled. Leave its key blank to keep the saved one.", size=12, color=MUTED),
        ], spacing=18, visible=False)
        self.header = header
        self.speech_settings_view = ft.Column([
            ft.Row([ft.IconButton(ft.Icons.ARROW_BACK, on_click=self.back_to_speaking),
                    ft.Text("Speech settings", size=24, color=INK, weight=ft.FontWeight.BOLD)]),
            ft.Text("Personalize your speech, one setting at a time.", size=13, color=MUTED),
            card(ft.Column([
                ft.Text("Voice", size=14, weight=ft.FontWeight.BOLD),
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.RECORD_VOICE_OVER, color=TEAL),
                    title=ft.Text("Choose or add a voice"),
                    subtitle=ft.Text("Manage saved voice profiles"),
                    trailing=ft.Icon(ft.Icons.CHEVRON_RIGHT),
                    on_click=self.show_voices),
                ft.Divider(),
                ft.Text("Expression", size=14, weight=ft.FontWeight.BOLD),
                self.expression, self.expression_note,
                ft.Divider(),
                self.speed_label, self.speed,
                self.safety_actions, self.safety_note,
                self.protection_note,
            ], spacing=12)),
            ft.OutlinedButton("Manage my voices", icon=ft.Icons.RECORD_VOICE_OVER,
                              on_click=self.show_voices),
        ], spacing=16, visible=False)
        nav_items = [
            ("Speak", ft.Icons.CHAT_BUBBLE_OUTLINE, self.back_to_speaking),
            ("Phrases", ft.Icons.BOOKMARK_BORDER, self.open_phrases),
            ("Voices", ft.Icons.RECORD_VOICE_OVER, self.show_voices),
            ("Settings", ft.Icons.TUNE, self.open_speech_settings),
        ]
        self.home_navigation = ft.Container(ft.Row([
            ft.TextButton(label, icon=icon, on_click=action,
                          style=ft.ButtonStyle(color=TEAL if label == "Speak" else MUTED))
            for label, icon, action in nav_items
        ], alignment=ft.MainAxisAlignment.SPACE_AROUND, spacing=0, wrap=True),
            padding=ft.padding.symmetric(horizontal=4, vertical=6),
            bgcolor=PANEL, border_radius=22, visible=False,
            border=ft.border.all(0.5, BORDER))
        self.language_pills = ft.Row(spacing=8, wrap=True)
        self.language_bar = ft.Column([ft.Text("Speak in", size=12, color=MUTED), self.language_pills], spacing=8, visible=False)
        self.status_pills = ft.Row(spacing=8, wrap=True)
        self.banner_title = ft.Text("Voice server is offline", size=14, color=RED, weight=ft.FontWeight.W_500)
        self.banner_detail = ft.Text("Reconnect to start speaking.", size=12, color=RED, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self.error_banner = ft.Container(ft.Row([ft.Icon(ft.Icons.ERROR_OUTLINE, color=RED, size=20),
            ft.Column([self.banner_title, self.banner_detail], expand=True, spacing=2),
            ft.TextButton("Connect", on_click=self.open_connection, style=ft.ButtonStyle(bgcolor=PANEL, color=RED,
                shape=ft.StadiumBorder()))], spacing=10), padding=16, border_radius=14, visible=False)
        self.screen_switcher = ft.AnimatedSwitcher(self.welcome_view, duration=180, reverse_duration=150,
            transition=ft.AnimatedSwitcherTransition.FADE, switch_in_curve=ft.AnimationCurve.EASE_OUT)
        self.screen_body = ft.Column([self.screen_switcher], scroll=ft.ScrollMode.HIDDEN, expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.speech_actions = ft.Column([ft.Row([self.speak_button, self.stop_button], spacing=10)], visible=False)
        self.activity = ft.Column([self.progress, self.status], spacing=4, visible=False)
        self.shell = ft.Column([header, self.status_pills, self.language_bar, self.screen_body,
            self.voice_actions, self.speech_actions, self.error_banner, self.activity, self.home_navigation], spacing=12, expand=True)
        page.add(ft.Container(expand=True, alignment=ft.alignment.top_center,
            content=ft.Container(width=420, content=self.shell)))
        self.render_language_pills()
        self.show_screen("welcome")
        page.on_disconnect = self.shutdown
        page.on_close = self.shutdown
        page.on_connect = self.reconnect
        page.on_resized = self.layout_resized
        self.apply_layout()
        self.update_controls()

    def apply_layout(self):
        # Use logical viewport height, so Windows display scaling and phone keyboards
        # do not force the full desktop-sized layout into a smaller visible area.
        height = getattr(self.page, "height", None)
        compact = isinstance(height, (int, float)) and height < 760
        self.page.padding = 12 if compact else 16
        self.shell.spacing = 8 if compact else 12
        self.input.min_lines = self.preview.min_lines = 1 if compact else 2
        self.input.max_lines = 3 if compact else 4
        self.preview.max_lines = 3 if compact else 5
        self.welcome_spacer.height = 12 if compact else 32
        self.welcome_logo.width = self.welcome_logo.height = 160 if compact else 210

    async def layout_resized(self, event=None):
        self.apply_layout()
        self.update()

    async def change_view(self, event=None):
        index = self.navigation.selected_index
        if event is not None and getattr(event, "data", None) in {"0", "1"}:
            index = int(event.data)
            self.navigation.selected_index = index
        self.show_screen("compose" if index == 0 else "library")
        if index == 1:
            await self.load_phrase_bank()

    def show_screen(self, name):
        self.screen = name
        for key, view in (("welcome", self.welcome_view),
                          ("language_setup", self.language_setup_view),
                          ("security_setup", self.security_setup_view),
                          ("connection", self.connection_view),
                          ("voices", self.voices_view), ("ready", self.ready_view),
                          ("compose", self.compose_view), ("library", self.library_view),
                          ("speech_settings", self.speech_settings_view)):
            view.visible = key == name
            if key == name:
                self.screen_switcher.content = view
        self.header.visible = self.connection.visible = name not in {"welcome", "language_setup", "security_setup", "ready"}
        self.home_navigation.visible = name in {"compose", "library", "voices", "speech_settings"} and not self.onboarding_active
        self.language_bar.visible = name in {"compose", "library"}
        self.speech_actions.visible = name == "compose"
        self.voice_actions.visible = name == "voices"
        self.activity.visible = name in {"compose", "library"}
        self.status_pills.visible = name in {"compose", "library", "voices", "speech_settings"}
        self.update_chrome()
        if name != "connection":
            self.colab_key_field.value = self.groq_field.value = ""
        self.update()

    async def get_started(self, event=None):
        if not self.busy:
            self.show_screen("language_setup")

    async def onboarding_urdu(self, event=None):
        self.language.value = "ur"
        await self.language_changed()

    async def onboarding_english(self, event=None):
        if "en" in [option.key for option in self.language.options]:
            self.language.value = "en"
            await self.language_changed()
        else:
            self.say_status("English speech requires a compatible model. Urdu remains selected.")

    async def onboarding_language_continue(self, event=None):
        self.show_screen("security_setup")

    async def onboarding_security_continue(self, event=None):
        self.show_screen("voices")

    async def finish_onboarding(self, event=None):
        self.onboarding_active = False
        self.show_screen("compose")

    async def back_to_speaking(self, event=None):
        self.navigation.selected_index = 0
        self.show_screen("compose")

    async def open_phrases(self, event=None):
        self.navigation.selected_index = 1
        self.show_screen("library")
        await self.load_phrase_bank()

    async def open_speech_settings(self, event=None):
        self.show_screen("speech_settings")

    async def show_voices(self, event=None):
        if not self.busy:
            self.show_screen("voices")

    async def use_aria_voice(self, event=None):
        if self.busy:
            return
        self.voice.value = "aria_builtin"
        self.navigation.selected_index = 0
        self.show_screen("ready" if self.onboarding_active else "compose")
        self.update_controls()
        profile = self.selected_voice()
        if not profile or not profile.get("available", False):
            self.say_status("ARIA Default Voice needs a licensed synthetic reference configured on the backend. No personal recording is required.", error=True)

    async def expression_changed(self, event=None):
        self.expression_note.value = ("Manual expression selected. A missing style reference uses a clearly reported neutral fallback."
            if self.expression.value != "auto" else "Automatic suggestions never override an explicitly selected expression.")
        self.phrase_signature = None
        self.phrase_expression_label.value = "Expression · " + self.expression.value.title()
        self.speech_emotion_label.value = self.expression.value.title()
        self.phrase_expression_note.value = self.expression_note.value
        if self.screen == "library":
            await self.load_phrase_bank()
        self.update()

    async def copy_message(self, event=None):
        text = self.preview.value if self.native_override or self.preview_phase == "complete" else self.input.value
        if (text or "").strip():
            self.page.set_clipboard(text)
            self.say_status("Message copied.")

    async def continue_speaking(self, event=None):
        if self.busy:
            return
        voice = self.selected_voice()
        if not voice or voice.get("needs_reenrollment"):
            self.voice_note.value = "Add a recording or select a compatible voice to continue."
            self.update()
            return
        self.navigation.selected_index = 0
        self.show_screen("ready" if self.onboarding_active else "compose")

    async def open_connection(self, event=None):
        if not self.busy:
            self.show_screen("connection")

    async def save_colab(self, event=None):
        if self.busy:
            return
        for field in (self.colab_url_field, self.colab_key_field, self.groq_field):
            field.error_text = None
        validating_groq = False
        try:
            url, key = parse_colab_outputs(self.colab_url_field.value, self.colab_key_field.value)
            validating_groq = True
            groq = validate_key((self.groq_field.value or "").strip())
        except ValueError as error:
            message = str(error)
            field = self.groq_field if validating_groq else self.colab_url_field if any(
                word in message.lower() for word in ("url", "address", "port")) else self.colab_key_field
            field.error_text = message
            self.connect_error.value = ""
            self.update()
            return
        self.busy = True
        self.connect_button.disabled = self.connect_progress.visible = True
        self.connect_error.value = "Checking your running Colab model…"
        self.connect_error.color = MUTED
        self.update_controls()
        try:
            await self.client.connect_colab(url, key, groq)
            self.colab_key_field.value = self.groq_field.value = ""
            self.connect_error.value = "Connected. Your settings are saved securely on this computer."
            await self.refresh()
            self.show_screen("voices")
        except AppError as error:
            self.connect_error.value = str(error)
            self.connect_error.tooltip = str(error)
            self.connect_error.color = RED
        finally:
            self.busy = False
            self.connect_button.disabled = self.connect_progress.visible = False
            self.update_controls()

    async def toggle_theme(self, event=None):
        dark = self.page.theme_mode != ft.ThemeMode.DARK
        self.page.theme_mode = ft.ThemeMode.DARK if dark else ft.ThemeMode.LIGHT
        self.theme_button.icon = ft.Icons.LIGHT_MODE_OUTLINED if dark else ft.Icons.DARK_MODE_OUTLINED
        self.update_chrome()
        self.update()

    def update(self):
        if not self.closed:
            if hasattr(self, "connect_error"):
                self.connect_error.visible = bool(self.connect_error.value)
            self.page.update()

    def say_status(self, text, error=False):
        self.status_error = error
        self.status.value, self.status.color = text, RED if error else MUTED
        self.update_chrome()
        self.update()

    def update_chrome(self):
        dark = self.page.theme_mode == ft.ThemeMode.DARK
        self.status_pills.controls = [status_pill("Ready to speak" if self.server_ready else "Voice unavailable", self.server_ready, dark)]
        self.status_pills.visible = self.screen in {"compose", "library", "voices", "speech_settings"} and not self.server_ready
        self.error_banner.bgcolor = "#351E20" if dark else "#FFF1F0"
        self.error_banner.visible = self.screen in {"compose", "library"} and (not self.server_ready or self.status_error)
        self.banner_title.value = "Voice server is offline" if not self.server_ready else "Unable to finish"
        self.banner_detail.value = "Reconnect to start speaking." if not self.server_ready else "Check your connection and try again."
        self.banner_detail.tooltip = self.status.value if self.status_error else None
        self.status.visible = self.busy and not self.status_error

    async def auto_mode(self, event=None):
        await self.select_mode("auto")

    async def native_mode(self, event=None):
        await self.select_mode("native")

    async def select_mode(self, value):
        self.mode.value = value
        await self.mode_changed()

    def render_language_pills(self):
        controls = []
        for code in ("en", "ur"):
            async def select(event, value=code):
                self.language.value = value
                await self.language_changed()
            active = self.language.value == code
            controls.append(ft.OutlinedButton(self.language_names.get(code, code), on_click=select, height=44,
                style=ft.ButtonStyle(bgcolor=INK if active else PANEL, color=BG if active else INK,
                    padding=ft.padding.symmetric(horizontal=18), side=ft.BorderSide(0.5, BORDER),
                    text_style=ft.TextStyle(size=15, weight=ft.FontWeight.W_500 if active else ft.FontWeight.W_400),
                    shape=ft.StadiumBorder(), animation_duration=180)))
        items = []
        for code, name in self.language_names.items():
            if code in {"en", "ur"}:
                continue
            async def choose(event, value=code):
                self.language.value = value
                await self.language_changed()
            items.append(ft.PopupMenuItem(text=name, on_click=choose))
        if not items:
            items.append(ft.PopupMenuItem(text="Connect to discover more languages", on_click=self.open_connection))
        other = self.language.value not in {"en", "ur"}
        controls.append(ft.PopupMenuButton(content=ft.Container(ft.Row([
            ft.Text(self.language_names.get(self.language.value, "More") if other else "More", size=15,
                color=BG if other else INK), ft.Icon(ft.Icons.EXPAND_MORE, size=18, color=BG if other else MUTED)], tight=True),
            padding=ft.padding.symmetric(horizontal=14, vertical=12), border_radius=100,
            border=ft.border.all(0.5, BORDER), bgcolor=INK if other else PANEL, animate=180), items=items))
        self.language_pills.controls = controls

    def selected_voice(self):
        return next((v for v in self.voices if v["id"] == self.voice.value), None)

    def update_controls(self):
        self.start_button.disabled = self.busy
        self.welcome_status.value = "Checking your connection…" if self.busy else "Made for your everyday conversations."
        self.char_count.value = f"{len(self.input.value or '')} / {self.settings.max_text_chars}"
        self.native_count.value = f"{len(self.preview.value or '')} / {self.settings.max_text_chars}"
        self.mode_pill.disabled = self.language_pills.disabled = self.busy
        selected = self.selected_voice()
        valid_voice = selected is not None and not selected.get("needs_reenrollment", False) and selected.get("available", True)
        if selected and self.workflow_mode == "assistive" and selected.get("authorization_status") in {"review_required", "revoked"}:
            valid_voice = False
        authorized = self.workflow_mode != "research" or self.security_mode != "strict" or self.voice.value == "aria_builtin" or self.client.session_valid(self.voice.value)
        speech_text = self.preview.value if self.native_override else self.input.value
        self.speak_button.disabled = self.busy or not (speech_text or "").strip() or not valid_voice or not authorized
        self.verify_button.visible = self.workflow_mode == "research" and self.security_mode != "off" and self.voice.value != "aria_builtin"
        self.verify_button.disabled = self.busy or not valid_voice
        self.emotion_button.visible = self.emotion_enabled
        self.emotion_button.disabled = self.busy or not valid_voice or not authorized or self.voice.value == "aria_builtin"
        self.safety_note.value = ("Verify this voice before speaking." if self.security_mode == "strict" and not authorized
                                 else "Voice verification is optional." if self.security_mode == "basic" else "")
        self.safety_note.visible = bool(self.safety_note.value)
        self.safety_actions.visible = self.verify_button.visible or self.emotion_button.visible
        self.voice_continue.disabled = self.busy
        for control in (self.voice, self.enroll_button, self.refresh_button, self.settings_button, self.speed, self.mode, self.language, self.expression, self.phrase_expression, self.account_button, self.use_aria_button):
            control.disabled = self.busy
        self.progress.visible = self.busy
        self.stop_button.disabled = self.audio is None
        self.add_phrase_button.disabled = self.busy
        for control, needs_voice in self.phrase_controls:
            control.disabled = self.busy or (needs_voice and (not valid_voice or not authorized))
        self.voice_note.value = ("This voice needs a new recording. Enroll it again." if selected and not valid_voice
                                 else "Long recordings are supported. Use one clear speaker." if not self.voices else "")
        if selected and selected.get("kind") == "builtin" and not selected.get("available"):
            self.voice_note.value = "ARIA Default Voice is not configured. Supply a licensed synthetic reference manifest on the backend."
        elif selected and selected.get("authorization_status") == "review_required" and self.workflow_mode == "assistive":
            self.voice_note.value = "This older profile needs authorized re-enrollment to record provenance and checkpoint compatibility. Existing data is preserved."
        elif selected and selected.get("authorization_status") == "revoked":
            self.voice_note.value = "Authorization for this voice was revoked. Use ARIA Voice or another currently authorized profile."
        self.voice_note.visible = bool(self.voice_note.value)
        self.library_voice.value = (f'{self.language_names.get(self.language.value, self.language.value)} · {selected["name"]}' if selected
                                    else "Choose a voice to speak your phrases.")
        self.update()

    def cancel_preview(self):
        self.revision += 1
        self.preview_request_key = None
        self.preview_phase = None
        if self.preview_task:
            self.preview_task.cancel()
            self.preview_task = None
        if self.predict_task:
            self.predict_task.cancel()
            self.predict_task = None
        self.suggestion_row.controls.clear()

    def align_input(self):
        is_urdu = self.language.value == "ur" and (self.mode.value == "urdu" or (self.mode.value == "auto" and
            any("\u0600" <= c <= "\u06ff" for c in (self.input.value or ""))))
        rtl = is_urdu or (self.language.value in {"ar", "fa", "he"} and
            (self.mode.value in {"native", "urdu"} or any("\u0590" <= c <= "\u06ff" for c in (self.input.value or ""))))
        self.input.text_align = ft.TextAlign.RIGHT if rtl else ft.TextAlign.LEFT
        self.input.rtl = rtl
        self.input.text_style = ft.TextStyle(font_family=self.font if is_urdu else None)

    async def text_changed(self, event=None):
        self.native_override = False
        self.align_input()
        self.schedule_preview()
        self.update_controls()

    async def text_blurred(self, event=None):
        if not self.native_override:
            self.schedule_preview(immediate=True)

    async def native_changed(self, event=None):
        # A native edit never updates the Roman controller or triggers another conversion.
        self.cancel_preview()
        self.native_override = True
        self.preview_note.value = "Your edited native text will be spoken."
        self.preview_note.visible = True
        self.update_controls()

    async def mode_changed(self, event=None):
        self.native_override = False
        self.mode_pill.content.content.controls[0].value = "Native script" if self.mode.value in {"urdu", "native"} else "Auto-convert"
        self.configure_language_ui()
        self.schedule_preview(immediate=True)

    def configure_language_ui(self):
        code = self.language.value
        name = self.language_names.get(code, code)
        self.mode.visible = True
        scripts = {"ur": "اردو", "hi": "हिन्दी", "ar": "العربية", "ja": "日本語", "ko": "한국어",
            "zh-cn": "中文", "ru": "Русский", "en": "English", "es": "Español", "fr": "Français",
            "de": "Deutsch", "it": "Italiano", "pt": "Português", "tr": "Türkçe"}
        self.source_title.value = f"Roman {name} input" if self.mode.value not in {"native", "urdu"} else f"{name} input"
        self.input.hint_text = f"Type {name} using Roman letters…" if self.mode.value not in {"native", "urdu"} else f"Type {name} text…"
        self.preview_title.value = f"{name} native text · {scripts[code]}" if code in scripts and scripts[code] != name else f"{name} native text"
        self.preview.text_style = ft.TextStyle(font_family=self.font if code == "ur" else None)
        self.preview.hint_text = f"Converted {name} text appears here"
        self.preview.rtl = code in {"ur", "ar", "fa", "he"}
        self.preview.text_align = ft.TextAlign.RIGHT if self.preview.rtl else ft.TextAlign.LEFT
        self.conversion_note.value = (f"Automatic {name} conversion by Groq. Your text is sent to the API."
            if self.api_translit_enabled else "Urdu conversion uses the local dictionary. Add a Groq key in Connect for automatic conversion in other languages."
            if code == "ur" else f"Type {name} in its native script, or add a Groq key in Connect for automatic conversion.")
        self.align_input()
        self.render_language_pills()

    async def language_changed(self, event=None):
        self.native_override = False
        self.configure_language_ui()
        self.schedule_preview(immediate=True)
        self.phrase_revision += 1
        self.phrase_language = None
        self.phrase_signature = None
        self.phrases = []
        self.render_phrase_grid()
        if self.screen == "library":
            await self.load_phrase_bank()

    def schedule_preview(self, immediate=False):
        text = (self.input.value or "").strip()
        key = (self.input.value or "", self.language.value, self.mode.value)
        if key == self.preview_request_key and self.preview_phase in {"running", "complete"}:
            return
        self.cancel_preview()
        self.preview_request_key = key
        self.preview_phase = "waiting"
        if self.language.value == "ur" and self.mode.value not in {"urdu", "native"} and not self.closed:
            self.predict_task = asyncio.create_task(self.get_suggestions(self.input.value or "", self.revision))
        if not text:
            self.preview.value = ""
            self.native_count.value = f"0 / {self.settings.max_text_chars}"
            self.preview_phase = "complete"
            self.preview_note.value = "Preview appears as you type."
            self.preview_note.visible = False
            self.update()
            return
        self.preview_note.value = "Updating preview…"
        self.preview_note.visible = True
        self.update()
        if not self.closed:
            self.preview_task = asyncio.create_task(self.get_preview(text, self.revision, immediate))

    async def get_preview(self, text, revision, immediate):
        try:
            language, mode = self.language.value, self.mode.value
            if not immediate:
                await asyncio.sleep(self.settings.preview_delay_ms / 1000)
            if revision != self.revision:
                return
            self.preview_phase = "running"
            if mode in {"urdu", "native"}:
                result = text
            elif language == "ur":
                result = await self.client.preview(text)
            elif self.api_translit_enabled:
                result = await self.client.preview(text, language, mode)
            else:
                result = text
            if revision == self.revision and not self.closed and not self.native_override:
                self.preview.value = result
                self.preview_phase = "complete"
                self.native_count.value = f"{len(result)} / {self.settings.max_text_chars}"
                self.preview_note.value = "Check the wording before speaking."
                needs_key = self.language.value != "ur" and not self.api_translit_enabled and self.mode.value not in {"native", "urdu"}
                self.preview_note.visible = needs_key
                if needs_key:
                    self.preview_note.value = "Add a Groq key in Connect to convert phonetic text."
                self.update()
        except asyncio.CancelledError:
            pass
        except AppError as error:
            if revision == self.revision and not self.closed:
                self.preview_phase = "failed"
                self.preview.value = ""
                self.preview_note.value = str(error)
                self.preview_note.visible = True
                self.update()

    async def refresh(self, preferred=None):
        if self.closed:
            return
        self.busy = True
        self.update_controls()
        try:
            self.voices = await self.client.voices()
            self.voice.options = [ft.dropdown.Option(v["id"], v["name"] +
                (" · needs re-enrollment" if v.get("needs_reenrollment") else "")) for v in self.voices]
            compatible = [v["id"] for v in self.voices if not v.get("needs_reenrollment") and v.get("available", True)]
            previous = preferred or self.voice.value
            self.voice.value = previous if previous in compatible else (compatible[0] if compatible else None)
            health = await self.client.health()
            self.backend_ready = True
            self.security_mode = health.get("security_mode", "off")
            self.workflow_mode = health.get("workflow_mode", "assistive")
            research_audio = self.workflow_mode == "research" and health.get("watermark_policy") == "research_unprotected"
            for note in (self.protection_note, self.library_protection_note):
                note.value = "Research mode · audio may be unprotected. Not normal deployment." if research_audio else "Required audio protection · unverified output is withheld."
                note.color = RED if research_audio else MUTED
            if hasattr(self.client, "account"):
                self.access_state = await self.client.account()
            built = health.get("builtin_voice", {})
            if built:
                self.builtin_note.value = ("Generic synthetic voice ready to initialize. New speech still needs Colab."
                    if built.get("available") else "Not configured yet: a licensed synthetic reference is needed on the backend. Do not upload another person's recording as the generic voice.")
            self.emotion_enabled = health.get("emotion_enabled", False)
            self.api_translit_enabled = health.get("transliteration", {}).get("api_enabled", False)
            catalog = health.get("languages", {})
            if catalog.get("items"):
                self.language_names = {"en": "English", "ur": "Urdu", **{item["code"]: item["name"]
                    for item in health.get("preview_languages", [])}, **{item["code"]: item["name"] for item in catalog["items"]}}
                self.language.options = [ft.dropdown.Option(code, name) for code, name in self.language_names.items()]
                if self.language.value not in self.language_names:
                    self.language.value = catalog.get("default", "ur")
                self.language_note.visible = not catalog.get("discovered", False)
            self.reference_limits = health.get("reference_limits", self.reference_limits)
            self.configure_language_ui()
            ready = health["colab"].get("reachable") is True
            self.server_ready = ready
            await self.load_phrase_bank(warm=bool(self.voice.value))
            self.connection.value = "Connected · voice server ready" if ready else "Backend connected · voice server offline"
            self.connection.color = TEAL if ready else MUTED
            self.say_status("Ready when you are." if self.voice.value else "Enroll your voice to begin.")
        except AppError as error:
            self.server_ready = False
            self.backend_ready = False
            self.connection.value, self.connection.color = "Connection needs attention", RED
            self.say_status(str(error), error=True)
        finally:
            self.busy = False
            self.update_controls()

    async def refresh_clicked(self, event=None):
        if not self.busy:
            await self.refresh()

    async def voice_changed(self, event=None):
        self.update_controls()
        await self.load_phrase_bank(warm=bool(self.voice.value))

    async def speed_changed(self, event=None):
        self.speed_label.value = f"Speaking speed · {self.speed.value:.1f}×"
        for phrase in self.phrases:
            phrase["cached"] = False
        self.render_phrase_grid()
        self.update()

    async def speed_committed(self, event=None):
        await self.load_phrase_bank()

    async def speak_clicked(self, event=None):
        if self.busy or self.closed:
            return
        selected = self.selected_voice()
        text = ((self.preview.value if self.native_override else self.input.value) or "").strip()
        speech_mode = "native" if self.native_override else self.mode.value
        if not text or not selected or selected.get("needs_reenrollment"):
            self.say_status("Enter a message and choose an enrolled voice.", error=True)
            return
        self.cancel_preview()
        revision = self.revision
        self.release_audio()
        self.busy = True
        self.update_controls()
        self.say_status("Preparing your voice…")
        try:
            raw, urdu = await self.client.speak(text, selected["id"], float(self.speed.value), speech_mode, self.language.value, self.expression.value)
            if self.closed:
                return
            if self.revision == revision and urdu:
                self.preview.value, self.preview_note.value = urdu, "Text sent to your voice."
            self.play_audio(raw)
            expression = getattr(self.client, "last_expression", {})
            self.expression_note.value = ("The selected style has no suitable reference; this output uses neutral expression."
                if expression.get("method") == "neutral_fallback" else "Reference-conditioned expression; perceived emotion is not yet clinically or listener validated.")
            await self.load_phrase_bank()
        except AppError as error:
            self.say_status(str(error), error=True)
        finally:
            self.busy = False
            self.update_controls()

    def release_audio(self):
        if self.audio_watch:
            self.audio_watch.cancel()
            self.audio_watch = None
        audio, self.audio = self.audio, None
        if audio is not None:
            try:
                audio.pause()
                audio.release()
            except (AssertionError, RuntimeError):
                pass  # The native window may already have disconnected.
            if audio in self.page.overlay:
                self.page.overlay.remove(audio)

    def play_audio(self, raw):
        self.release_audio()
        self.audio_loaded = False
        audio = fta.Audio(src_base64=base64.b64encode(raw).decode("ascii"), autoplay=True,
                          release_mode=ReleaseMode.RELEASE)
        async def loaded(event):
            if self.audio is audio and not self.closed:
                self.audio_loaded = True
                self.say_status("Playing your message…")
        async def state_changed(event):
            if self.audio is not audio or self.closed:
                return
            if event.state == fta.AudioState.PLAYING:
                self.audio_loaded = True
                self.say_status("Speaking…")
            elif event.state == fta.AudioState.COMPLETED:
                self.release_audio()
                self.say_status("Finished. Ready for your next message.")
                self.update_controls()
        audio.on_loaded, audio.on_state_changed = loaded, state_changed
        self.audio = audio
        self.page.overlay.append(audio)
        self.say_status("Loading audio…")
        self.update_controls()
        self.audio_watch = asyncio.create_task(self.watch_audio(audio))

    async def watch_audio(self, audio):
        try:
            await asyncio.sleep(self.settings.audio_load_timeout)
            if self.audio is audio and not self.audio_loaded and not self.closed:
                # Avoid cancelling this task from inside release_audio().
                self.audio_watch = None
                self.release_audio()
                self.say_status("Audio did not start. Check your speaker output and try again.", error=True)
                self.update_controls()
        except asyncio.CancelledError:
            pass

    async def stop_clicked(self, event=None):
        self.release_audio()
        self.say_status("Playback stopped.")
        self.update_controls()

    async def open_enrollment(self, event=None):
        if self.busy:
            return
        self.selected_file = None
        self.dialog_kind = "enroll"
        self.enroll_name = ft.TextField(label="Voice name", max_length=80, autofocus=True)
        self.file_label = ft.Text("No audio selected", color=MUTED, selectable=True)
        self.enroll_error = ft.Text("", color=RED)
        self.choose_button = ft.OutlinedButton("Choose audio", icon=ft.Icons.AUDIO_FILE, height=52, on_click=self.choose_file)
        self.save_voice_button = ft.ElevatedButton("Enroll", height=52, on_click=self.save_voice)
        self.cancel_enroll_button = ft.TextButton("Cancel", height=52, on_click=self.close_dialog)
        self.enroll_source = ft.Dropdown(label="Recording source", value="historical", options=[
            ft.dropdown.Option("historical", "Historical recording"), ft.dropdown.Option("current", "Existing current recording")])
        self.enroll_basis = ft.Dropdown(label="Authorization basis", value="patient_consent", options=[
            ft.dropdown.Option("patient_consent", "Patient consent"),
            ft.dropdown.Option("authorized_representative", "Authorized representative process")])
        self.enroll_reference = ft.TextField(label="Authorization reference", hint_text="Brief basis/reference; do not upload sensitive documents", max_length=240)
        self.enroll_confirm = ft.Checkbox(label="I confirm appropriate authorization for this person's voice. A recording alone is not consent.", value=False)
        self.enroll_grant = ft.TextField(label="Existing patient authorization ID (for caregiver import)")
        self.grant_button = ft.TextButton("Create authorization only", on_click=self.create_enrollment_grant)
        self.dialog = ft.AlertDialog(modal=True, title=ft.Text("Enroll your voice"), content=ft.Column([
            ft.Text(self.reference_help()), self.enroll_name,
            self.choose_button, self.file_label,
            ft.Text("Use an authorized historical recording. You do not need to speak or record a new sample.", size=13, color=MUTED),
            self.enroll_source, self.enroll_basis, self.enroll_reference, self.enroll_confirm, self.enroll_grant, self.grant_button,
            self.enroll_error,
        ], tight=True, width=400, scroll=ft.ScrollMode.AUTO),
            actions=[self.cancel_enroll_button, self.save_voice_button])
        self.page.open(self.dialog)

    async def enrollment_authorization(self):
        existing = (self.enroll_grant.value or "").strip()
        if existing:
            return existing
        if not self.enroll_confirm.value or not (self.enroll_reference.value or "").strip():
            raise AppError("Confirm the authorization basis and reference, or supply a patient-issued authorization ID.")
        return await self.client.authorize_recording(self.selected_file, self.enroll_source.value,
            self.enroll_basis.value, self.enroll_reference.value.strip())

    async def create_enrollment_grant(self, event=None):
        if self.busy or self.selected_file is None:
            return
        self.busy = True
        try:
            self.enroll_grant.value = await self.enrollment_authorization()
            self.enroll_error.value = "Authorization created for this exact file. A scoped caregiver may use this ID."
        except AppError as error:
            self.enroll_error.value = str(error)
        finally:
            self.busy = False
            self.update_controls()

    def reference_help(self):
        minutes = self.reference_limits["max_source_seconds"] / 60
        megabytes = min(self.reference_limits["max_upload_bytes"], self.settings.max_upload_bytes) / (1024 * 1024)
        window = self.reference_limits["window_seconds"]
        return (f"Upload up to {minutes:g} minutes / {megabytes:g} MB of one speaker. "
                f"The backend scans it and selects a clear section of up to {window:g} seconds for cloning. "
                "MP3, M4A, AAC, OGG, FLAC and WAV are accepted.")

    async def choose_file(self, event=None):
        extensions = ["wav"] if self.dialog_kind == "verify" else ["wav", "mp3", "m4a", "aac", "ogg", "flac"]
        self.picker.pick_files(dialog_title="Choose an audio recording", allow_multiple=False,
                               file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=extensions)

    async def file_selected(self, event):
        if self.dialog_kind not in {"enroll", "verify", "emotion"} or self.dialog is None or not self.dialog.open or self.busy or not getattr(event, "files", None):
            return
        self.selected_file = None
        self.file_label.value = "No audio selected"
        selected = event.files[0]
        if not selected.path or str(selected.path).startswith("content:"):
            self.enroll_error.value = "Save the audio to this device's Downloads folder, then choose it again."
            self.update()
            return
        if selected.size > self.settings.max_upload_bytes:
            self.enroll_error.value = "That file is too large. Choose a shorter recording."
            self.update()
            return
        self.selected_file = Path(selected.path)
        self.file_label.value = selected.name
        self.enroll_error.value = ""
        if self.dialog_kind == "enroll" and not (self.enroll_name.value or "").strip():
            self.enroll_name.value = Path(selected.name).stem[:80]
        self.update()

    async def save_voice(self, event=None):
        if self.busy:
            return
        name = (self.enroll_name.value or "").strip()
        if not name or len(name) > 80 or self.selected_file is None:
            self.enroll_error.value = "Enter a voice name and choose an audio file."
            self.update()
            return
        self.cancel_preview()
        self.busy = True
        for control in (self.save_voice_button, self.cancel_enroll_button, self.choose_button, self.enroll_name):
            control.disabled = True
        self.enroll_error.value = "Creating your voice profile…"
        self.update_controls()
        try:
            grant = await self.enrollment_authorization()
            identifier = await self.client.enroll(self.selected_file, name, grant)
        except AppError as error:
            self.enroll_error.value = str(error)
        else:
            if self.closed:
                return
            self.page.close(self.dialog)
            self.selected_file = None
            await self.refresh(preferred=identifier)
            self.say_status("Your voice has been enrolled. Type a message and tap Speak.")
        finally:
            self.busy = False
            for control in (self.save_voice_button, self.cancel_enroll_button, self.choose_button, self.enroll_name):
                control.disabled = False
            self.update_controls()

    async def close_dialog(self, event=None):
        if not self.busy and self.dialog:
            if self.dialog_kind == "account":
                self.account_pin.value = self.account_recovery.value = self.account_result.value = ""
            self.page.close(self.dialog)
            self.selected_file = None
            self.dialog_kind = None

    async def open_verification(self, event=None):
        if self.busy or not self.voice.value:
            return
        self.busy = True
        self.update_controls()
        try:
            self.challenge_data = await self.client.challenge(self.voice.value)
            self.dialog_kind, self.selected_file = "verify", None
            self.file_label, self.enroll_error = ft.Text("No WAV selected", color=MUTED), ft.Text("", color=RED)
            self.verify_submit = ft.ElevatedButton("Check recording", height=52, on_click=self.submit_verification)
            self.verify_cancel = ft.TextButton("Cancel", height=52, on_click=self.close_dialog)
            self.verify_choose = ft.OutlinedButton("Choose challenge WAV", height=52, on_click=self.choose_file)
            self.dialog = ft.AlertDialog(modal=True, title=ft.Text("Verify your voice"), content=ft.Column([
                ft.Text("Read this exact phrase aloud. Record a short WAV in another app, then choose it here."),
                ft.Text(self.challenge_data["phrase"], font_family=self.font, rtl=True, text_align=ft.TextAlign.RIGHT, size=24),
                ft.Text(f"Upload and verification must finish within {self.challenge_data.get('expires_in', 60)} seconds. Each challenge can be used once."),
                self.verify_choose, self.file_label, self.enroll_error,
                ft.Text("These checks are best-effort and may reject genuine speech. They are not suitable for everyone with speech inability.", size=12, color=MUTED),
            ], width=440, tight=True, scroll=ft.ScrollMode.AUTO), actions=[self.verify_cancel, self.verify_submit])
            self.page.open(self.dialog)
        except AppError as error:
            self.say_status(str(error), error=True)
        finally:
            self.busy = False
            self.update_controls()

    async def submit_verification(self, event=None):
        if self.busy or self.selected_file is None:
            return
        self.busy = True
        for control in (self.verify_submit, self.verify_cancel, self.verify_choose):
            control.disabled = True
        self.enroll_error.value = "Checking the phrase and speaker…"
        self.update_controls()
        try:
            seconds = await self.client.verify(self.challenge_data["challenge_id"], self.selected_file)
            self.page.close(self.dialog)
            self.selected_file = None
            self.say_status(f"Voice verified for {int(seconds)} seconds.")
        except AppError as error:
            self.enroll_error.value = str(error) + " Close this dialog and request a new challenge."
        finally:
            self.busy = False
            self.verify_cancel.disabled = False
            # A submitted challenge is single-use, including failed submissions.
            self.update_controls()

    async def open_emotion(self, event=None):
        if self.busy or not self.voice.value:
            return
        self.dialog_kind, self.selected_file = "emotion", None
        self.file_label, self.enroll_error = ft.Text("No WAV selected", color=MUTED), ft.Text("", color=RED)
        self.emotion_tag = ft.Dropdown(label="Reference style", value="happy", options=[
            ft.dropdown.Option(tag, tag.title()) for tag in ("neutral", "happy", "sad", "calm", "angry")])
        self.emotion_submit = ft.ElevatedButton("Save reference", height=52, on_click=self.save_emotion)
        self.emotion_cancel = ft.TextButton("Cancel", height=52, on_click=self.close_dialog)
        self.emotion_choose = ft.OutlinedButton("Choose reference audio", height=52, on_click=self.choose_file)
        self.enroll_source = ft.Dropdown(label="Recording source", value="historical", options=[ft.dropdown.Option("historical", "Historical recording"), ft.dropdown.Option("current", "Existing current recording")])
        self.enroll_basis = ft.Dropdown(label="Authorization basis", value="patient_consent", options=[ft.dropdown.Option("patient_consent", "Patient consent"), ft.dropdown.Option("authorized_representative", "Authorized representative process")])
        self.enroll_reference = ft.TextField(label="Authorization reference", max_length=240)
        self.enroll_confirm = ft.Checkbox(label="This recording has appropriate authorization for the same voice owner.", value=False)
        self.enroll_grant = ft.TextField(label="Patient authorization ID (if provided)")
        self.dialog = ft.AlertDialog(modal=True, title=ft.Text("Add emotion reference"), content=ft.Column([
            ft.Container(height=8), self.emotion_tag,
            ft.Text(self.reference_help() + " This replaces the selected style's previous reference."),
            self.emotion_choose, self.file_label, self.enroll_error,
            self.enroll_source, self.enroll_basis, self.enroll_reference, self.enroll_confirm, self.enroll_grant,
            ft.Text("Use existing authorized audio; no patient is required to record new emotion samples.", size=12, color=MUTED),
            ft.Text("XTTS has no native emotion control. Any effect depends on the reference clip and may be subtle.", size=12, color=MUTED),
        ], width=440, tight=True, scroll=ft.ScrollMode.AUTO), actions=[self.emotion_cancel, self.emotion_submit])
        self.page.open(self.dialog)

    async def save_emotion(self, event=None):
        if self.busy or self.selected_file is None:
            return
        self.busy = True
        for control in (self.emotion_submit, self.emotion_cancel, self.emotion_choose):
            control.disabled = True
        self.enroll_error.value = "Preparing the reference…"
        self.update_controls()
        try:
            grant = await self.enrollment_authorization()
            await self.client.add_emotion(self.voice.value, self.emotion_tag.value, self.selected_file, grant)
            self.page.close(self.dialog)
            self.selected_file = None
            await self.load_phrase_bank()
            self.say_status("Reference saved. The phrase cache is being refreshed.")
        except AppError as error:
            self.enroll_error.value = str(error)
        finally:
            self.busy = False
            for control in (self.emotion_submit, self.emotion_cancel, self.emotion_choose):
                control.disabled = False
            self.update_controls()

    async def open_settings(self, event=None):
        if self.busy:
            return
        self.dialog_kind = "settings"
        self.url_field = ft.TextField(label="Backend address", value=self.settings.backend_url,
                                     keyboard_type=ft.KeyboardType.URL)
        self.key_field = ft.TextField(label="Backend key", helper_text="Optional", value=self.settings.api_key,
                                     password=True, can_reveal_password=True)
        self.settings_error = ft.Text("", color=RED)
        self.dialog = ft.AlertDialog(modal=True, title=ft.Text("Connection settings"), content=ft.Column([
            ft.Container(height=8), self.url_field, self.key_field,
            ft.Text("On a phone, use your laptop's LAN address, for example http://192.168.1.10:8001. Both devices must be on the same network.", size=13),
            ft.Text("Changes last for this app session. The key is never saved on this device by the app.", size=13, color=MUTED),
            self.settings_error,
        ], tight=True, width=400, scroll=ft.ScrollMode.AUTO), actions=[
            ft.TextButton("Cancel", height=52, on_click=self.close_dialog),
            ft.ElevatedButton("Save & connect", height=52, on_click=self.save_settings)])
        self.page.open(self.dialog)

    async def open_account(self, event=None):
        if self.busy:
            return
        try:
            status = await self.client.account()
        except AppError as error:
            self.say_status(str(error), error=True)
            return
        self.access_state = status
        self.dialog_kind = "account"
        self.account_id = ft.TextField(label="Account ID", value="patient")
        self.account_pin = ft.TextField(label="PIN (6–12 digits)", password=True, can_reveal_password=True)
        self.account_recovery = ft.TextField(label="Recovery code (recovery only)", password=True, can_reveal_password=True)
        self.account_result = ft.Text("", selectable=True, size=13)
        self.caregiver_permissions = [ft.Checkbox(label=name, value=False) for name in ("speak", "enroll", "manage")]
        self.caregiver_rows = ft.Column(spacing=4)
        self.account_dialog = ft.AlertDialog(modal=True, title=ft.Text("Accessible local account"),
            content=ft.Column([ft.Text("The device key protects this installation. A PIN adds a speech-free account lock. Caregiver login does not grant patient consent."),
                self.account_id, self.account_pin, self.account_recovery,
                ft.Row([ft.TextButton("Unlock", on_click=self.unlock_account), ft.TextButton("Set patient PIN", on_click=self.setup_account),
                    ft.TextButton("Lock", on_click=self.lock_account), ft.TextButton("Recover", on_click=self.recover_account)], wrap=True),
                ft.Divider(), ft.Text("Patient: create scoped caregiver access using the PIN above."),
                ft.Row(self.caregiver_permissions, wrap=True), ft.TextButton("Add caregiver", on_click=self.add_caregiver_account),
                self.caregiver_rows, self.account_result], tight=True, width=400, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Close", on_click=self.close_dialog)])
        self.dialog = self.account_dialog
        if (status.get("actor") or {}).get("role") == "patient":
            try:
                for item in await self.client.account("caregivers"):
                    if not item["active"]:
                        continue
                    async def revoke(event, identifier=item["id"]):
                        try:
                            await self.client.revoke_caregiver(identifier)
                            self.account_result.value = "Caregiver access revoked."
                            event.control.disabled = True
                            self.update()
                        except AppError as error:
                            self.account_result.value = str(error)
                            self.update()
                    self.caregiver_rows.controls.append(ft.TextButton("Revoke " + item["id"], on_click=revoke))
            except AppError:
                pass
        self.page.open(self.dialog)

    async def account_action(self, action):
        if self.busy:
            return
        self.busy = True
        self.update_controls()
        try:
            values = {}
            if action in {"setup", "login"}:
                values = {"actor_id": self.account_id.value or "patient", "pin": self.account_pin.value or ""}
            elif action == "recover":
                values = {"recovery_code": self.account_recovery.value or "", "pin": self.account_pin.value or ""}
            elif action == "caregivers":
                values = {"pin": self.account_pin.value or "", "permissions": [c.label for c in self.caregiver_permissions if c.value]}
            result = await self.client.account(action, **values)
            self.account_pin.value = self.account_recovery.value = ""
            if result.get("recovery_code"):
                self.account_result.value = "Save this recovery code privately; it is shown only now:\n" + result["recovery_code"]
            elif action == "caregivers":
                self.account_result.value = "Caregiver account: " + result["actor_id"] + ". Only selected permissions were granted."
            else:
                self.account_result.value = "Account locked." if action == "logout" else "Account unlocked."
            await self.refresh()
        except AppError as error:
            self.account_result.value = str(error)
        finally:
            self.busy = False
            self.update_controls()

    async def unlock_account(self, event=None):
        await self.account_action("login")

    async def setup_account(self, event=None):
        await self.account_action("setup")

    async def lock_account(self, event=None):
        await self.account_action("logout")

    async def recover_account(self, event=None):
        await self.account_action("recover")

    async def add_caregiver_account(self, event=None):
        await self.account_action("caregivers")

    async def save_settings(self, event=None):
        if self.busy:
            return
        try:
            settings = replace(self.settings, backend_url=backend_origin(self.url_field.value or ""),
                               api_key=validate_key(self.key_field.value or ""))
        except ValueError as error:
            self.settings_error.value = str(error)
            self.update()
            return
        self.busy = True
        self.cancel_preview()
        self.release_audio()
        old_client = self.client
        self.settings, self.client = settings, BackendClient(settings)
        self.phrase_revision += 1
        self.phrases = []
        self.render_phrase_grid()
        self.voices, self.voice.options, self.voice.value = [], [], None
        self.page.close(self.dialog)
        # Do not leave the key in a retained dialog control after applying it.
        self.key_field.value = ""
        await old_client.close()
        await self.refresh()
        self.schedule_preview(immediate=True)

    async def shutdown(self, event=None):
        if self.closed:
            return
        self.closed = True
        self.cancel_preview()
        if self.phrase_poll_task:
            self.phrase_poll_task.cancel()
            self.phrase_poll_task = None
        self.release_audio()
        await self.client.close()

    async def reconnect(self, event=None):
        if self.closed:
            self.closed = False
            self.client = BackendClient(self.settings)
            await self.refresh()
            self.start_phrase_poll()

    async def get_suggestions(self, prefix, revision):
        try:
            await asyncio.sleep(self.settings.predict_delay_ms / 1000)
            words = await self.client.predict(prefix)
            if revision != self.revision or self.closed:
                return
            controls = []
            for word in words:
                async def choose(event, value=word):
                    if revision != self.revision or (self.input.value or "") != prefix or self.native_override:
                        return
                    updated = insert_suggestion(self.input.value or "", value)
                    if len(updated) > self.settings.max_text_chars:
                        self.say_status("The message is at its character limit. Shorten it before adding a suggestion.", error=True)
                        return
                    self.input.value = updated
                    await self.text_changed()
                controls.append(ft.TextButton(content=ft.Text(word, color=INK, size=14), on_click=choose,
                    tooltip="Add suggestion", height=40, style=ft.ButtonStyle(bgcolor=SOFT, color=INK,
                        shape=ft.StadiumBorder(), side=ft.BorderSide(0.5, BORDER),
                        padding=ft.padding.symmetric(horizontal=14), animation_duration=150)))
            self.suggestion_row.controls = controls
            self.update()
        except asyncio.CancelledError:
            pass
        except AppError:
            if revision == self.revision:
                self.suggestion_row.controls.clear()
                self.update()  # Suggestions are optional; never hide a useful speech error.

    async def load_phrase_bank(self, warm=False):
        if self.closed:
            return
        self.phrase_revision += 1
        revision = self.phrase_revision
        language = self.language.value
        selected = self.selected_voice()
        voice_id = self.voice.value if selected and not selected.get("needs_reenrollment") else None
        try:
            if warm and voice_id and language == "ur":
                await self.client.warm_phrases(voice_id)
            if self.phrase_language != language:
                self.phrase_status.value = f"Preparing phrases in {self.language_names.get(language, language)}…"
                self.update()
            result = await self.client.phrases(voice_id, float(self.speed.value), language, self.expression.value)
            if self.closed or revision != self.phrase_revision or language != self.language.value:
                return
            self.phrases = result["items"]
            self.phrase_language = language
            ready = sum(bool(p.get("cached")) for p in self.phrases)
            self.phrase_status.value = (f"{len(self.phrases)} phrases · {ready} ready offline" if voice_id else "Choose a voice to speak these phrases.")
            # Polling must not recreate every button and reset scrolling when nothing changed.
            signature = repr((language, voice_id, self.speed.value, self.expression.value, self.phrases))
            if signature != self.phrase_signature:
                self.phrase_signature = signature
                self.render_phrase_grid()
            else:
                self.update()
        except AppError as error:
            if revision == self.phrase_revision and not self.closed:
                self.phrase_status.value = str(error)
                # Clear stale entries when switching servers or losing the bank.
                self.phrases = []
                self.phrase_signature = None
                self.render_phrase_grid()

    def render_phrase_grid(self):
        mode = self.phrase_filter.value
        phrases = [p for p in self.phrases if mode == "all" or (mode == "favorites" and p.get("favorite"))
                   or (mode == "recent" and p.get("last_used")) or p["category"] == mode]
        query = (self.phrase_search.value or "").strip().lower()
        if query:
            phrases = [p for p in phrases if query in p["roman"].lower() or query in p["urdu"] or query in p.get("display_text", "").lower()]
        if mode == "recent":
            phrases.sort(key=lambda p: p["last_used"], reverse=True)
            phrases = phrases[:20]
        self.phrase_grid.controls, self.phrase_controls = [], []
        for phrase in phrases:
            async def speak(event, identifier=phrase["id"]):
                await self.play_phrase(identifier)
            async def favorite(event, item=phrase):
                await self.toggle_favorite(item)
            async def edit(event, item=phrase):
                await self.open_phrase_editor(item)
            code = self.language.value
            target = phrase.get("display_text", phrase["urdu"])
            rtl = code in {"ur", "ar", "fa", "he"}
            play = ft.TextButton(content=ft.Column([
                ft.Text(target, size=20 if code == "ur" else 16, font_family=self.font if code == "ur" else None,
                        rtl=rtl, text_align=ft.TextAlign.RIGHT if rtl else ft.TextAlign.LEFT),
                ft.Text("Ready to play" if phrase.get("cached") else "Tap to speak", size=11, color=MUTED),
            ], tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH), on_click=speak,
                expand=True, tooltip=target, style=ft.ButtonStyle(color=INK, padding=12,
                    shape=ft.RoundedRectangleBorder(radius=14)))
            star = ft.IconButton(ft.Icons.STAR if phrase.get("favorite") else ft.Icons.STAR_BORDER,
                tooltip="Remove favorite" if phrase.get("favorite") else "Add favorite", on_click=favorite,
                icon_color=TEAL, width=44, height=44)
            edit_button = ft.IconButton(ft.Icons.EDIT_OUTLINED, tooltip="Edit original phrase", on_click=edit, width=44, height=44)
            self.phrase_controls.extend([(play, True), (star, False), (edit_button, False)])
            self.phrase_grid.controls.append(card(ft.Row([play, ft.Column([star, edit_button], spacing=0)], spacing=0), padding=4))
        if not phrases:
            self.phrase_grid.controls.append(ft.Text("No phrases in this view yet.", color=MUTED))
        self.update_controls()

    async def phrase_filter_changed(self, event=None):
        self.render_phrase_grid()

    async def play_phrase(self, identifier):
        if self.busy or self.closed or not self.voice.value:
            return
        self.cancel_preview()
        self.release_audio()
        self.busy = True
        self.update_controls()
        self.say_status("Preparing your phrase…")
        try:
            raw, urdu = await self.client.speak_phrase(identifier, self.voice.value, float(self.speed.value), self.language.value, self.expression.value)
            if not self.closed:
                self.play_audio(raw)
                expression = getattr(self.client, "last_expression", {})
                self.phrase_expression_note.value = ("No matching style reference is available; this phrase uses neutral expression."
                    if expression.get("method") == "neutral_fallback" else "Reference-conditioned expression; listener evaluation is still required.")
                self.say_status("Playing your phrase.")
                await self.load_phrase_bank()
        except AppError as error:
            self.say_status(str(error), error=True)
        finally:
            self.busy = False
            self.update_controls()

    async def toggle_favorite(self, phrase):
        if self.busy:
            return
        self.busy = True
        self.update_controls()
        try:
            await self.client.save_phrase(phrase["id"], {"favorite": not phrase.get("favorite", False)})
            await self.load_phrase_bank()
        except AppError as error:
            self.say_status(str(error), error=True)
        finally:
            self.busy = False
            self.update_controls()

    async def add_phrase(self, event=None):
        await self.open_phrase_editor()

    async def open_phrase_editor(self, phrase=None):
        if self.busy:
            return
        self.dialog_kind = "phrase"
        self.editing_phrase = phrase["id"] if phrase else None
        self.phrase_roman = ft.TextField(label="Roman Urdu", value=phrase["roman"] if phrase else "",
                                       max_length=180, multiline=True, min_lines=1, max_lines=3)
        self.phrase_urdu = ft.TextField(label="Urdu", value=phrase["urdu"] if phrase else "", max_length=180,
            multiline=True, min_lines=2, max_lines=4, text_align=ft.TextAlign.RIGHT, rtl=True,
            text_style=ft.TextStyle(font_family=self.font))
        self.phrase_category = ft.Dropdown(label="Category", value=phrase["category"] if phrase else "custom",
            options=[ft.dropdown.Option(c, c.title()) for c in ("needs", "medical", "family", "greetings", "custom")])
        self.phrase_error = ft.Text("", color=RED)
        self.phrase_save = ft.ElevatedButton("Save", height=52, on_click=self.save_phrase_editor)
        self.phrase_delete = ft.TextButton("Delete", height=52, on_click=self.delete_phrase_editor, visible=bool(phrase))
        self.phrase_cancel = ft.TextButton("Cancel", height=52, on_click=self.close_dialog)
        self.dialog = ft.AlertDialog(modal=True, title=ft.Text("Edit phrase" if phrase else "Add phrase"),
            content=ft.Column([ft.Container(height=8), self.phrase_roman, self.phrase_urdu, self.phrase_category,
                ft.Text("Enter both versions. Tap Delete to remove this phrase permanently.", size=12, color=MUTED),
                self.phrase_error], width=440, tight=True, scroll=ft.ScrollMode.AUTO),
            actions=[self.phrase_delete, self.phrase_cancel, self.phrase_save])
        self.page.open(self.dialog)

    async def save_phrase_editor(self, event=None):
        if not (self.phrase_roman.value or "").strip() or not (self.phrase_urdu.value or "").strip():
            self.phrase_error.value = "Enter both Roman Urdu and Urdu text."
            self.update()
            return
        await self.change_phrase(delete=False)

    async def delete_phrase_editor(self, event=None):
        await self.change_phrase(delete=True)

    async def change_phrase(self, delete):
        if self.busy:
            return
        self.busy = True
        for control in (self.phrase_save, self.phrase_delete, self.phrase_cancel):
            control.disabled = True
        self.update_controls()
        try:
            if delete:
                await self.client.delete_phrase(self.editing_phrase)
            else:
                await self.client.save_phrase(self.editing_phrase, {"roman": self.phrase_roman.value.strip(),
                    "urdu": self.phrase_urdu.value.strip(), "category": self.phrase_category.value})
            self.page.close(self.dialog)
            await self.load_phrase_bank()
            self.say_status("Phrase deleted." if delete else "Phrase saved.")
        except AppError as error:
            self.phrase_error.value = str(error)
        finally:
            self.busy = False
            for control in (self.phrase_save, self.phrase_delete, self.phrase_cancel):
                control.disabled = False
            self.update_controls()

    def start_phrase_poll(self):
        if self.phrase_poll_task:
            self.phrase_poll_task.cancel()
        async def poll():
            try:
                while not self.closed:
                    await asyncio.sleep(self.settings.phrase_refresh_seconds)
                    if not self.busy and self.screen == "library" and (self.dialog is None or not self.dialog.open):
                        await self.load_phrase_bank()
            except asyncio.CancelledError:
                pass
        self.phrase_poll_task = asyncio.create_task(poll())


async def main(page: ft.Page):
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    try:
        settings = AppSettings.from_env()
    except ValueError as error:
        page.title, page.theme_mode = "A.R.I.A", ft.ThemeMode.DARK
        page.add(ft.Text("Check your app configuration", size=26), ft.Text(str(error)))
        return
    app = AriaApp(page, settings)
    await app.refresh()
    app.start_phrase_poll()


if __name__ == "__main__":
    ft.app(target=main, assets_dir=str(ASSETS), host="127.0.0.1")
