"""Utilities for managing Discord voice connections, TTS playback, and STT hotword detection."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from collections import defaultdict
from typing import Awaitable, Callable, Dict, Optional

import audioop
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
            if self._is_speech(data):
                asyncio.create_task(self._process(member, data))

    @staticmethod
    def _is_speech(pcm: bytes) -> bool:
        """Return True if the PCM data likely contains speech."""

        try:
            rms = audioop.rms(pcm, 2)
        except audioop.error:
            return False
        return rms > 200

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
        self._idle_tasks: Dict[int, asyncio.Task[None]] = {}
        self._last_activity: Dict[int, float] = defaultdict(lambda: time.monotonic())
        self._idle_timeout = 300.0

    def set_hotword_callback(self, callback: HotwordCallback) -> None:
        self._listener.set_callback(callback)

    async def ensure_voice_client(self, member: discord.Member) -> Optional[discord.VoiceClient]:
        if member.voice is None or member.voice.channel is None:
            return None

        channel = member.voice.channel
        guild = member.guild
        voice_client = guild.voice_client

        try:
            if voice_client and voice_client.channel != channel:
                await voice_client.move_to(channel)
            elif not voice_client:
                voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)
                sink = voice_recv.BasicSink(lambda user, data: self._on_voice_frame(guild, user, data))
                voice_client.listen(sink)
            elif isinstance(voice_client, voice_recv.VoiceRecvClient) and not voice_client.is_listening():
                sink = voice_recv.BasicSink(lambda user, data: self._on_voice_frame(guild, user, data))
                voice_client.listen(sink)
        except Exception:
            logger.exception("ボイスチャンネルへの接続に失敗しました")
            return None

        if voice_client:
            self._mark_active(guild.id)
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
            self._mark_active(guild_id)
            with tempfile.NamedTemporaryFile("wb", delete=False, suffix=".wav") as tmp:
                tmp.write(audio)
                path = tmp.name
            try:
                source = discord.FFmpegPCMAudio(path)
                voice_client.play(source)
                while voice_client.is_playing():
                    await asyncio.sleep(0.25)
                    self._mark_active(guild_id)
            finally:
                try:
                    os.remove(path)
                except OSError:
                    logger.warning("一時ファイル %s の削除に失敗しました", path)

    def _mark_active(self, guild_id: int) -> None:
        self._last_activity[guild_id] = time.monotonic()
        task = self._idle_tasks.get(guild_id)
        if task is None or task.done():
            self._idle_tasks[guild_id] = asyncio.create_task(self._watch_idle(guild_id))

    async def _watch_idle(self, guild_id: int) -> None:
        try:
            while True:
                await asyncio.sleep(30)
                guild = self._bot.get_guild(guild_id)
                if guild is None:
                    return
                voice_client = guild.voice_client
                if voice_client is None:
                    return
                idle = time.monotonic() - self._last_activity.get(guild_id, 0)
                if idle >= self._idle_timeout:
                    try:
                        await voice_client.disconnect(force=True)
                        logger.info("ギルド %s で 5 分間の無音を検知したため VC から切断しました", guild_id)
                    except Exception:
                        logger.exception("VC 切断に失敗しました")
                    finally:
                        return
        finally:
            self._idle_tasks.pop(guild_id, None)

    def _on_voice_frame(
        self,
        guild: discord.Guild,
        user: Optional[discord.User],
        data: voice_recv.VoiceData,
    ) -> None:
        if not isinstance(user, discord.Member):
            member = guild.get_member(user.id) if user is not None else None
        else:
            member = user

        if member is None:
            return

        pcm = data.pcm or b""
        if not pcm:
            return

        self._mark_active(guild.id)
        self._listener.feed(member, pcm)
