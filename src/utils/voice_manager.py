"""Utilities for managing Discord voice connections, TTS playback, and STT hotword detection."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from collections import defaultdict
from typing import Awaitable, Callable, Dict, Optional

import discord
from discord.ext import voice_recv

from .stt_client import WhisperClient
from .tts_client import VoiceVoxClient

logger = logging.getLogger(__name__)

HotwordCallback = Callable[[discord.Member, str], Awaitable[None]]


class HotwordListener:
    """Listens to PCM frames and detects the ORALLM hotword."""

    def __init__(self, stt_client: WhisperClient) -> None:
        self._stt = stt_client
        self._buffers: Dict[int, bytearray] = defaultdict(bytearray)
        self._processing: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._callback: Optional[HotwordCallback] = None

    def set_callback(self, callback: HotwordCallback) -> None:
        self._callback = callback

    def feed(self, member: Optional[discord.Member], pcm: bytes) -> None:
        if member is None or not pcm:
            return
        buffer = self._buffers[member.id]
        buffer.extend(pcm)
        # Process roughly every ~2 seconds of audio (assuming 48kHz 16-bit stereo -> 192000 bytes/sec)
        if len(buffer) >= 384000:
            data = bytes(buffer)
            self._buffers[member.id].clear()
            asyncio.create_task(self._process(member, data))

    async def _process(self, member: discord.Member, pcm: bytes) -> None:
        lock = self._processing[member.id]
        if lock.locked():
            return
        async with lock:
            try:
                transcript = await self._stt.transcribe_pcm(pcm)
            except Exception:
                logger.exception("音声認識に失敗しました")
                return

            if not transcript:
                return

            lower = transcript.lower()
            key = "orallm"
            if key not in lower:
                return

            index = lower.index(key)
            command = transcript[index + len(key) :].strip()
            if not command:
                return

            if self._callback:
                await self._callback(member, command)


class VoiceManager:
    """Manages Discord voice clients for playback and recording."""

    def __init__(self, bot: discord.Client, tts: VoiceVoxClient, stt: WhisperClient) -> None:
        self._bot = bot
        self._tts = tts
        self._stt = stt
        self._play_locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._listener = HotwordListener(stt)

    def set_hotword_callback(self, callback: HotwordCallback) -> None:
        self._listener.set_callback(callback)

    async def ensure_voice_client(self, member: discord.Member) -> Optional[discord.VoiceClient]:
        if member.voice is None or member.voice.channel is None:
            return None

        channel = member.voice.channel
        guild = member.guild
        voice_client = guild.voice_client

        if voice_client and voice_client.channel != channel:
            await voice_client.move_to(channel)
        elif not voice_client:
            voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)
            sink = voice_recv.BasicSink(lambda user, data: self._on_voice_frame(guild, user, data))
            voice_client.listen(sink)
        elif isinstance(voice_client, voice_recv.VoiceRecvClient) and not voice_client.is_listening():
            sink = voice_recv.BasicSink(lambda user, data: self._on_voice_frame(guild, user, data))
            voice_client.listen(sink)

        return voice_client

    async def play_tts(self, member: discord.Member, text: str) -> bool:
        voice_client = await self.ensure_voice_client(member)
        if voice_client is None:
            return False

        try:
            audio = await self._tts.synthesize(text)
        except Exception:
            logger.exception("VOICEVOX の読み上げに失敗しました")
            return False

        await self._play_audio(voice_client, audio)
        return True

    async def _play_audio(self, voice_client: discord.VoiceClient, audio: bytes) -> None:
        guild_id = voice_client.guild.id
        lock = self._play_locks[guild_id]
        async with lock:
            with tempfile.NamedTemporaryFile("wb", delete=False, suffix=".wav") as tmp:
                tmp.write(audio)
                path = tmp.name
            try:
                source = discord.FFmpegPCMAudio(path)
                voice_client.play(source)
                while voice_client.is_playing():
                    await asyncio.sleep(0.25)
            finally:
                try:
                    os.remove(path)
                except OSError:
                    logger.warning("一時ファイル %s の削除に失敗しました", path)

    def _on_voice_frame(
        self,
        guild: discord.Guild,
        user: Optional[discord.User],
        data: voice_recv.VoiceData,
    ) -> None:
        if not isinstance(user, discord.Member):
            # Attempt to resolve user -> member
            if user is not None:
                member = guild.get_member(user.id)
            else:
                member = None
        else:
            member = user

        if member is None:
            return

        pcm = data.pcm or b""
        if not pcm:
            return

        self._listener.feed(member, pcm)
