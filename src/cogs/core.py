"""Core cog defining the public slash commands."""

from __future__ import annotations

import logging
import os
import platform
import time

try:
    import resource  # type: ignore
except ImportError:  # pragma: no cover - platform specific
    resource = None  # type: ignore
from typing import Any, Optional

import discord
from discord import app_commands
from discord.ext import commands

from ..utils.link_client import LinkClient

logger = logging.getLogger(__name__)


class CoreCog(commands.Cog):
    """Primary slash commands for the ORA bot."""

    def __init__(self, bot: commands.Bot, link_client: LinkClient) -> None:
        self.bot = bot
        self._link_client = link_client

    @app_commands.command(name="ping", description="Botのレイテンシを確認します。")
    async def ping(self, interaction: discord.Interaction) -> None:
        """Return the websocket latency."""

        latency_ms = self.bot.latency * 1000
        await interaction.response.send_message(
            f"Pong! {latency_ms:.0f}ms", ephemeral=True
        )

    @app_commands.command(name="say", description="指定したメッセージを送信します。")
    @app_commands.describe(
        text="送信するメッセージ",
        ephemeral="エフェメラルで返信する場合は true",
    )
    async def say(
        self, interaction: discord.Interaction, text: str, ephemeral: bool = False
    ) -> None:
        """Send back the provided message if the invoker has administrator permission."""

        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "このコマンドはサーバー内でのみ使用できます。", ephemeral=True
            )
            return

        if not interaction.user.guild_permissions.administrator:
            raise app_commands.CheckFailure("管理者権限が必要です。")

        await interaction.response.send_message(text, ephemeral=ephemeral)

    @app_commands.command(name="link", description="ORAアカウントと連携します。")
    async def link(self, interaction: discord.Interaction) -> None:
        """Generate a single-use link code."""

        await interaction.response.defer(ephemeral=True, thinking=True)
        user_id = interaction.user.id
        try:
            code = await self._link_client.request_link_code(user_id)
        except Exception:  # noqa: BLE001 - send friendly message while logging separately
            logger.exception("Failed to generate link code", extra={"user_id": user_id})
            await interaction.followup.send(
                "リンクコードの生成に失敗しました。時間を置いて再度お試しください。",
                ephemeral=True,
            )
            return

        await interaction.followup.send(f"リンクコード: `{code}`", ephemeral=True)

    @app_commands.command(name="health", description="Botの状態を表示します。")
    async def health(self, interaction: discord.Interaction) -> None:
        """Return runtime information about the bot process."""

        uptime_seconds = time.time() - getattr(self.bot, "started_at", time.time())
        latency_ms = self.bot.latency * 1000
        guild_count = len(self.bot.guilds)
        pid = os.getpid()
        process_memory: Optional[str] = None

        if resource is not None:
            try:
                usage = resource.getrusage(resource.RUSAGE_SELF)
                # ru_maxrss is kilobytes on Linux/macOS
                process_memory = f"{usage.ru_maxrss / 1024:.1f} MiB"
            except (AttributeError, ValueError):
                process_memory = None

        lines = [
            f"PID: {pid}",
            f"Uptime: {uptime_seconds:.0f} 秒",
            f"Latency: {latency_ms:.0f} ms",
            f"Guilds: {guild_count}",
            f"Python: {platform.python_version()}",
            f"discord.py: {discord.__version__}",
        ]
        if process_memory:
            lines.append(f"Memory: {process_memory}")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @commands.Cog.listener()
    async def on_app_command_completion(
        self, interaction: discord.Interaction, command: app_commands.Command[Any, Any, Any]
    ) -> None:
        logger.info(
            "Command %s executed by %s (%s)",
            command.qualified_name,
            interaction.user,
            getattr(interaction.user, "id", "unknown"),
        )
