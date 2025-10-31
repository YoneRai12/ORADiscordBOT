"""Speech-to-text client backed by OpenAI Whisper."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import numpy as np

try:
    import whisper
except ImportError:  # pragma: no cover - optional dependency
    whisper = None  # type: ignore

logger = logging.getLogger(__name__)


class WhisperClient:
    """Wrapper that transcribes PCM audio using Whisper."""

    def __init__(self, model: str = "tiny", *, language: Optional[str] = "ja") -> None:
        self._model_name = model
        self._language = language
        self._model: Optional["whisper.Whisper"] = None
        self._load_lock = asyncio.Lock()

    async def _ensure_model(self) -> "whisper.Whisper":
        if whisper is None:
            raise RuntimeError("openai-whisper がインストールされていません。")
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is None:
                logger.info("Loading Whisper model %s", self._model_name)
                self._model = await asyncio.to_thread(whisper.load_model, self._model_name)
        return self._model

    async def transcribe_pcm(
        self,
        pcm_data: bytes,
        *,
        sample_rate: int = 48000,
        channels: int = 2,
    ) -> str:
        if not pcm_data:
            return ""

        model = await self._ensure_model()

        audio = np.frombuffer(pcm_data, np.int16).astype(np.float32)
        if channels > 1:
            audio = audio.reshape(-1, channels).mean(axis=1)
        audio = audio / np.max(np.abs(audio), initial=1.0)

        def _decode() -> str:
            mel = whisper.log_mel_spectrogram(audio)
            options = whisper.DecodingOptions(language=self._language, fp16=False)
            result = whisper.decode(model, mel, options)
            return result.text.strip()

        return await asyncio.to_thread(_decode)
