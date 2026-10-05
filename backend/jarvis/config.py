"""Validated, loopback-only runtime configuration. No cloud fallback."""

import json
import os
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


class Settings(BaseModel):
    provider: str = "ollama"
    api_base: str = "http://127.0.0.1:1234/v1"
    computer_control: bool = False
    news_enabled: bool = True
    news_priority: str = "india"
    model: str = "qwen3:4b-instruct"
    workflow_model: str = Field(
        default="qwen3:4b-instruct", min_length=1, max_length=100
    )
    language: str = "en"
    context_tokens: int = Field(default=4096, ge=4096, le=8192)
    timezone: str = "Asia/Kolkata"
    voice: str = "kokoro-af_heart"
    voice_pace: float = Field(default=1.0, ge=0.8, le=1.4)
    google_voice_enabled: bool = False
    google_search_enabled: bool = False
    google_tts_model: str = Field(
        default="gemini-3.8-flash-lite-tts",
        pattern=r"^gemini-(?:3\.8-flash(?:-lite)?-tts|3\.1-flash-tts-preview)$",
    )
    online_voice_enabled: bool = False
    online_voice_fallback: str = "none"
    groq_voice_rpm: int = Field(default=10, ge=1, le=60)
    update_checks: bool = True
    conversation_recall: bool = True
    child_mode: bool = False
    long_speech_sentences: int = Field(default=48, ge=6, le=80)
    response_tokens: int = Field(default=650, ge=320, le=4096)

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        ZoneInfo(value)
        return value

    @field_validator("provider")
    @classmethod
    def valid_provider(cls, value):
        if value not in {"ollama", "compatible"}:
            raise ValueError("Use ollama or compatible")
        return value

    @field_validator("news_priority")
    @classmethod
    def valid_news_priority(cls, value):
        if value not in {"india", "world"}:
            raise ValueError("Choose india or world for news priority")
        return value

    @field_validator("api_base")
    @classmethod
    def valid_endpoint(cls, value):
        from .providers import validate_endpoint

        return validate_endpoint(value)

    @field_validator("language")
    @classmethod
    def valid_language(cls, value):
        if value not in {"en", "bn", "auto"}:
            raise ValueError("Use en, bn or auto")
        return value

    @field_validator("voice")
    @classmethod
    def local_name(cls, value):
        if (
            not value
            or len(value) > 100
            or "/" in value
            or ".." in value
            or "cloud" in value.lower()
        ):
            raise ValueError("Only local engine identifiers are allowed")
        return value

    @field_validator("online_voice_fallback")
    @classmethod
    def valid_voice_fallback(cls, value):
        allowed = {
            "none",
            "kokoro-af_heart",
            "kokoro-bf_emma",
            "mac-Tara",
            "mac-Rishi",
            "en_US-ljspeech-high",
        }
        if value not in allowed:
            raise ValueError("Select a supported local fallback voice or none")
        return value

    @field_validator("model")
    @classmethod
    def model_identifier(cls, value):
        if not value or len(value) > 128 or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid model identifier")
        return value


DATA = Path(os.getenv("JARVIS_DATA", str(ROOT / "data"))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
os.chmod(DATA, 0o700)
DB_PATH = DATA / "jarvis.sqlite3"
PORT = int(os.getenv("JARVIS_PORT", "8765"))
ORIGIN = f"http://127.0.0.1:{PORT}"
OLLAMA = os.getenv("OLLAMA_URL", "http://127.0.0.1:11437")
WHISPER = os.getenv("WHISPER_URL", "http://127.0.0.1:8178")
for endpoint in (OLLAMA, WHISPER):
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ValueError("Inference URLs must use HTTP loopback")
MODELS = Path(os.getenv("JARVIS_MODELS", str(ROOT / "models"))).resolve()
VAD_PATH = MODELS / "silero_vad.onnx"
APPS = json.loads(
    os.getenv(
        "JARVIS_APPLICATIONS",
        '{"Calculator":"com.apple.calculator","TextEdit":"com.apple.TextEdit","Safari":"com.apple.Safari"}',
    )
)


def read_settings():
    path = DATA / "settings.json"
    return (
        Settings.model_validate_json(path.read_text())
        if path.exists()
        else Settings(model=os.getenv("JARVIS_MODEL", "qwen3:4b-instruct"))
    )


def save_settings(settings):
    path = DATA / "settings.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(settings.model_dump_json())
    temporary.replace(path)
