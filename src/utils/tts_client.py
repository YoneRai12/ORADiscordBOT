"""VOICEVOX text-to-speech client."""

from __future__ import annotations

import logging
from typing import Any, Dict

import aiohttp

logger = logging.getLogger(__name__)


class VoiceVoxClient:
    """Minimal VOICEVOX HTTP client that synthesises WAV audio from text."""

    def __init__(self, base_url: str, speaker_id: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._speaker_id = speaker_id

    async def synthesize(self, text: str) -> bytes:
        """Synthesise ``text`` into WAV audio bytes."""

        if not text.strip():
            raise ValueError("読み上げ対象のテキストが空です。")

        params = {"speaker": self._speaker_id}
        timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            query_url = f"{self._base_url}/audio_query"
            payload: Dict[str, Any] = {"text": text, "speaker": self._speaker_id}
            async with session.post(query_url, params=params, json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"VOICEVOX audio_query 失敗: {resp.status} {body}")
                query = await resp.json()

            synthesis_url = f"{self._base_url}/synthesis"
            async with session.post(synthesis_url, params=params, json=query) as resp2:
                if resp2.status != 200:
                    body = await resp2.text()
                    raise RuntimeError(f"VOICEVOX synthesis 失敗: {resp2.status} {body}")
                audio = await resp2.read()

        logger.debug("VOICEVOX synthesis completed (bytes=%d)", len(audio))
        return audio
