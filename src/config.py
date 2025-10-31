"""Configuration loading for the ORA Discord bot."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional


class ConfigError(RuntimeError):
    """Raised when configuration is invalid."""


@dataclass(frozen=True)
class Config:
    """Validated configuration for the bot."""

    token: str
    app_id: int
    ora_api_base_url: Optional[str]
    public_base_url: Optional[str]
    dev_guild_id: Optional[int]
    log_level: str
    db_path: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    privacy_default: str
    voicevox_api_url: str
    voicevox_speaker_id: int
    search_api_key: Optional[str]
    search_engine: Optional[str]
    speak_search_progress_default: int

    @classmethod
    def load(cls) -> "Config":
        """Load configuration from environment variables."""

        token = os.getenv("DISCORD_BOT_TOKEN")
        if not token:
            raise ConfigError("環境変数 DISCORD_BOT_TOKEN が未設定です。")

        app_id_raw = os.getenv("DISCORD_APP_ID")
        if not app_id_raw:
            raise ConfigError("環境変数 DISCORD_APP_ID が未設定です。")
        try:
            app_id = int(app_id_raw)
        except ValueError as exc:  # pragma: no cover - validation only
            raise ConfigError("DISCORD_APP_ID は数値で指定してください。") from exc

        ora_base_url = os.getenv("ORA_API_BASE_URL")
        if ora_base_url:
            ora_base_url = ora_base_url.rstrip("/")

        public_base_url = os.getenv("PUBLIC_BASE_URL")
        if public_base_url:
            public_base_url = public_base_url.rstrip("/")

        dev_guild_raw = os.getenv("ORA_DEV_GUILD_ID")
        dev_guild_id: Optional[int] = None
        if dev_guild_raw:
            try:
                dev_guild_id = int(dev_guild_raw)
            except ValueError as exc:  # pragma: no cover - validation only
                raise ConfigError("ORA_DEV_GUILD_ID は数値で指定してください。") from exc

        log_level_raw = os.getenv("LOG_LEVEL", "INFO").strip()
        if log_level_raw.isdigit():
            level_name = logging.getLevelName(int(log_level_raw))
            if not isinstance(level_name, str) or level_name not in logging.getLevelNamesMapping():
                raise ConfigError("LOG_LEVEL に不明な値が指定されています。")
            log_level = level_name
        else:
            log_level = log_level_raw.upper()
            if log_level not in logging.getLevelNamesMapping():
                raise ConfigError("LOG_LEVEL に不明な値が指定されています。")

        db_path = os.getenv("ORA_BOT_DB", "ora_bot.db")

        llm_base_url = os.getenv("LLM_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/")
        llm_api_key = os.getenv("LLM_API_KEY", "lm-studio")
        llm_model = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")

        privacy_default = os.getenv("PRIVACY_DEFAULT", "private").lower()
        if privacy_default not in {"private", "public"}:
            privacy_default = "private"

        voicevox_api_url = os.getenv("VOICEVOX_API_URL", "http://localhost:50021").rstrip("/")
        voicevox_speaker_raw = os.getenv("VOICEVOX_SPEAKER_ID", "1")
        try:
            voicevox_speaker_id = int(voicevox_speaker_raw)
        except ValueError as exc:  # pragma: no cover - validation only
            raise ConfigError("VOICEVOX_SPEAKER_ID は数値で指定してください。") from exc

        search_api_key_raw = os.getenv("SEARCH_API_KEY")
        search_api_key = search_api_key_raw.strip() if search_api_key_raw else None
        if search_api_key == "":
            search_api_key = None

        search_engine_raw = os.getenv("SEARCH_ENGINE")
        search_engine = search_engine_raw.strip() if search_engine_raw else None
        if search_engine == "":
            search_engine = None

        speak_search_default_raw = os.getenv("SPEAK_SEARCH_PROGRESS_DEFAULT", "0")
        try:
            speak_search_progress_default = int(speak_search_default_raw)
        except ValueError as exc:  # pragma: no cover - validation only
            raise ConfigError("SPEAK_SEARCH_PROGRESS_DEFAULT は 0 または 1 を指定してください。") from exc
        if speak_search_progress_default not in (0, 1):
            raise ConfigError("SPEAK_SEARCH_PROGRESS_DEFAULT は 0 または 1 を指定してください。")

        return cls(
            token=token,
            app_id=app_id,
            ora_api_base_url=ora_base_url,
            public_base_url=public_base_url,
            dev_guild_id=dev_guild_id,
            log_level=log_level,
            db_path=db_path,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
            privacy_default=privacy_default,
            voicevox_api_url=voicevox_api_url,
            voicevox_speaker_id=voicevox_speaker_id,
            search_api_key=search_api_key,
            search_engine=search_engine,
            speak_search_progress_default=speak_search_progress_default,
        )
