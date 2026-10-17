from pathlib import Path
import os
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


def private_config_dir():
    return Path(os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")) / "ARIA" / "config"


def backend_env_file():
    explicit = os.environ.get("ARIA_BACKEND_ENV_FILE")
    if explicit:
        return Path(explicit)
    private = private_config_dir() / "backend.env"
    return private if private.is_file() else ROOT / ".env"


def validate_colab_url(value: str, allow_http: bool = False) -> str:
    value = value.strip().rstrip("/")
    if not value:
        return ""
    url = urlsplit(value)
    if (not url.hostname or url.username or url.password or url.query or url.fragment
            or url.path or url.scheme not in ({"https", "http"} if allow_http else {"https"})):
        raise ValueError("Use an HTTPS server origin without credentials, path, query, or fragment")
    try:
        url.port
    except ValueError:
        raise ValueError("Invalid server port") from None
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=backend_env_file(), env_file_encoding="utf-8", extra="ignore",
                                      hide_input_in_errors=True)
    colab_url: str = ""
    colab_api_key: SecretStr = SecretStr("")
    allow_insecure_colab: bool = False
    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = "openai/gpt-oss-120b"
    llm_translit_enabled: bool = False
    translit_strategy: Literal["dictionary_first", "api_first"] = "dictionary_first"
    groq_max_response_bytes: int = Field(65536, ge=1024, le=1048576)
    translit_fallback_cache_seconds: int = Field(60, ge=1, le=3600)
    local_only: bool = True
    aria_key: SecretStr = SecretStr("")
    require_auth: bool = False
    allowed_hosts: list[str] = Field(default_factory=lambda: ["*"])
    allowed_origins: list[str] = Field(default_factory=list)
    docs_enabled: bool = False
    rate_limit_requests: int = Field(600, ge=1, le=10000)
    rate_limit_window_seconds: int = Field(60, ge=1, le=3600)
    auth_failure_limit: int = Field(12, ge=1, le=100)
    keep_raw_audio: bool = False
    security_mode: Literal["off", "basic", "strict"] = "off"
    model_version: str = "urdu-xtts-v1"
    lang_tag: str = "ar"
    language_aliases: dict[str, str] = Field(default_factory=dict)
    data_dir: Path = ROOT / "data"
    dictionary_path: Path = ROOT / "data" / "roman_urdu_dictionary.json"
    fernet_key: SecretStr = SecretStr("")
    host: str = "127.0.0.1"
    port: int = Field(8001, ge=1, le=65535)
    default_speed: float = Field(1.0, ge=0.5, le=2)
    default_temperature: float = Field(0.65, gt=0, le=1.5)
    chunk_max_chars: int = Field(180, ge=20, le=180)
    max_text_chars: int = Field(2000, ge=1, le=10000)
    gpu_concurrency: int = Field(2, ge=1, le=2)
    gpu_timeout_seconds: float = Field(120, gt=0)
    health_timeout_seconds: float = Field(5, gt=0)
    gpu_retries: int = Field(2, ge=0, le=5)
    retry_backoff_seconds: float = Field(0.5, ge=0, le=10)
    groq_timeout_seconds: float = Field(10, gt=0)
    groq_backoff_seconds: float = Field(0.3, ge=0, le=2)
    max_response_bytes: int = Field(16 * 1024 * 1024, ge=1024)
    max_upload_bytes: int = Field(256 * 1024 * 1024, ge=1024)
    max_request_bytes: int = Field(258 * 1024 * 1024, ge=1024)
    max_json_bytes: int = Field(1024 * 1024, ge=1024)
    max_parallel_uploads: int = Field(1, ge=1, le=4)
    max_inflight: int = Field(8, ge=1, le=64)
    body_timeout_seconds: float = Field(300, gt=0)
    min_reference_seconds: float = Field(6, gt=0)
    max_reference_seconds: float = Field(30, gt=0)
    max_source_seconds: float = Field(1800, gt=0, le=86400)
    reference_scan_step_seconds: float = Field(5, ge=0.5, le=10)
    min_reference_sr: int = Field(8000, ge=1000)
    max_reference_sr: int = Field(96000, ge=8000)
    reference_sample_rate: int = Field(22050, ge=8000)
    output_sample_rate: int = Field(24000, ge=8000)
    max_silence_ratio: float = Field(0.6, ge=0, le=1)
    silence_threshold: float = Field(0.01, gt=0, lt=1)
    max_clipping_ratio: float = Field(0.01, ge=0, le=1)
    silence_ms: int = Field(150, ge=0, le=2000)
    target_dbfs: float = Field(-20, ge=-60, le=-1)
    max_generated_seconds: float = Field(600, gt=0, le=1800)
    audio_cache_entries: int = Field(100, ge=0, le=10000)
    translit_cache_entries: int = Field(5000, ge=1)
    phrase_seed_path: Path = ROOT / "data" / "default_phrases.json"
    phrase_max_count: int = Field(500, ge=60, le=5000)
    phrase_prewarm_enabled: bool = True
    phrase_warm_retry_seconds: float = Field(30, ge=1)
    phrase_translation_timeout_seconds: float = Field(30, gt=0)
    prediction_history_limit: int = Field(1000, ge=1, le=10000)
    watermark_enabled: bool = False
    watermark_generator_path: Path = ROOT / "data/models/audioseal/generator_base.pth"
    watermark_detector_path: Path = ROOT / "data/models/audioseal/detector_base.pth"
    watermark_message_bits: str = "0100000101010010"
    watermark_threshold: float = Field(0.5, gt=0, lt=1)
    watermark_bit_threshold: float = Field(0.5, gt=0, lt=1)
    watermark_frame_threshold: float = Field(0.5, gt=0, lt=1)
    watermark_chunk_seconds: int = Field(10, ge=1, le=30)
    watermark_detect_max_seconds: float = Field(120, ge=1, le=600)
    watermark_retry_seconds: float = Field(60, ge=1)
    safety_cpu_threads: int = Field(2, ge=1, le=16)
    safety_cache_dir: Path = ROOT / "data/models/runtime"
    liveness_whisper_path: Path = ROOT / "data/models/whisper-small"
    liveness_speaker_path: Path = ROOT / "data/models/ecapa"
    liveness_model_version: str = "ecapa-voxceleb-v1"
    liveness_language: str = "ur"
    liveness_beam_size: int = Field(1, ge=1, le=5)
    liveness_vad_filter: bool = True
    liveness_compute_type: Literal["int8", "float32"] = "int8"
    liveness_transcript_threshold: float = Field(0.8, gt=0, le=1)
    liveness_speaker_threshold: float = Field(0.65, ge=-1, le=1)
    liveness_challenge_seconds: int = Field(60, ge=5, le=60)
    liveness_session_seconds: int = Field(300, ge=10, le=3600)
    liveness_max_pending: int = Field(100, ge=1, le=1000)
    liveness_min_seconds: float = Field(1, gt=0)
    liveness_max_seconds: float = Field(20, gt=0, le=30)
    emotion_enabled: bool = False
    emotion_speed_delta: float = Field(0.05, ge=0, le=0.1)
    emotion_temperature_delta: float = Field(0.03, ge=0, le=0.1)
    safety_whisper_repo: str = "Systran/faster-whisper-small"
    safety_speaker_repo: str = "speechbrain/spkrec-ecapa-voxceleb"
    safety_watermark_repo: str = "facebook/audioseal"

    @model_validator(mode="after")
    def check_settings(self):
        key = self.aria_key.get_secret_value()
        if self.require_auth and len(key) < 32:
            raise ValueError("REQUIRE_AUTH needs an ARIA_KEY of at least 32 characters")
        if key and (not key.isascii() or any(c.isspace() for c in key)):
            raise ValueError("ARIA_KEY must be ASCII without whitespace")
        if self.host not in {"127.0.0.1", "localhost", "::1"} and len(key) < 32:
            raise ValueError("Non-loopback binding requires a strong ARIA_KEY")
        self.colab_url = validate_colab_url(self.colab_url, self.allow_insecure_colab)
        if self.min_reference_seconds > self.max_reference_seconds or self.min_reference_sr > self.max_reference_sr:
            raise ValueError("Reference minimums must not exceed maximums")
        if self.max_request_bytes <= self.max_upload_bytes:
            raise ValueError("MAX_REQUEST_BYTES must leave room for multipart headers")
        if not self.model_version.strip() or not self.lang_tag.strip():
            raise ValueError("MODEL_VERSION and LANG_TAG must be nonempty")
        if not self.language_aliases:
            self.language_aliases = {"ur": self.lang_tag}
        elif self.language_aliases.get("ur") != self.lang_tag:
            raise ValueError("LANGUAGE_ALIASES must map ur to LANG_TAG")
        if self.max_source_seconds < self.min_reference_seconds:
            raise ValueError("MAX_SOURCE_SECONDS must allow the minimum reference duration")
        if len(self.watermark_message_bits) != 16 or set(self.watermark_message_bits) - {"0", "1"}:
            raise ValueError("WATERMARK_MESSAGE_BITS must contain exactly 16 binary digits")
        if self.liveness_min_seconds > self.liveness_max_seconds:
            raise ValueError("Liveness minimum duration exceeds maximum")
        return self
