"""Core cog defining the public slash commands."""

from __future__ import annotations

import logging
import os
import platform
import time
from typing import Any, Optional

try:
    import resource  # type: ignore
except ImportError:  # pragma: no cover - platform specific
    resource = None  # type: ignore

import discord
from discord import app_commands
from discord.ext import commands

from ..storage import Store
from ..utils.link_client import LinkClient

logger = logging.getLogger(__name__)


class CoreCog(commands.Cog):
    """Primary slash commands for the ORA bot."""

    def __init__(
        self,
        bot: commands.Bot,
        *,
        link_client: LinkClient,
        store: Store,
        privacy_default: str,
        speak_default: int,
    ) -> None:
        self.bot = bot
        self._link_client = link_client
        self._store = store
        self._privacy_default = privacy_default
        self._speak_default = speak_default

    async def _resolve_ephemeral(
        self, interaction: discord.Interaction, override: Optional[bool]
    ) -> bool:
        await self._store.ensure_user(
            interaction.user.id,
            privacy_default=self._privacy_default,
            speak_search_default=self._speak_default,
        )
        if override is not None:
            return override
        privacy = await self._store.get_privacy(interaction.user.id)
        return privacy == "private"

    @app_commands.command(name="ping", description="Botのレイテンシを確認します。")
    @app_commands.describe(ephemeral="true を指定するとエフェメラルで返信します")
    async def ping(self, interaction: discord.Interaction, ephemeral: Optional[bool] = None) -> None:
        """Return the websocket latency."""

        ephemeral_flag = await self._resolve_ephemeral(interaction, ephemeral)
        latency_ms = self.bot.latency * 1000
        await interaction.response.send_message(
            f"Pong! {latency_ms:.0f}ms", ephemeral=ephemeral_flag
        )

    @app_commands.command(name="say", description="指定したメッセージを送信します。")
    @app_commands.describe(
        text="送信するメッセージ",
        ephemeral="true を指定するとエフェメラルで返信します",
    )
    async def say(
        self,
        interaction: discord.Interaction,
        text: str,
        ephemeral: Optional[bool] = None,
    ) -> None:
        """Send back the provided message if the invoker has administrator permission."""

        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "このコマンドはサーバー内でのみ使用できます。", ephemeral=True
            )
            return

        if not interaction.user.guild_permissions.administrator:
            raise app_commands.CheckFailure("管理者権限が必要です。")

        ephemeral_flag = await self._resolve_ephemeral(interaction, ephemeral)
        await interaction.response.send_message(text, ephemeral=ephemeral_flag)

    @app_commands.command(name="link", description="ORAアカウントと連携します。")
    @app_commands.describe(ephemeral="true を指定するとエフェメラルで返信します")
    async def link(self, interaction: discord.Interaction, ephemeral: Optional[bool] = None) -> None:
        """Generate a single-use link code."""

        ephemeral_flag = await self._resolve_ephemeral(interaction, ephemeral)
        await interaction.response.defer(ephemeral=ephemeral_flag, thinking=True)
        user_id = interaction.user.id
        try:
            code = await self._link_client.request_link_code(user_id)
        except Exception:  # noqa: BLE001 - send friendly message while logging separately
            logger.exception("Failed to generate link code", extra={"user_id": user_id})
            await interaction.followup.send(
                "リンクコードの生成に失敗しました。時間を置いて再度お試しください。",
                ephemeral=ephemeral_flag,
            )
            return

        await interaction.followup.send(f"リンクコード: `{code}`", ephemeral=ephemeral_flag)

    @app_commands.command(name="health", description="Botの状態を表示します。")
    @app_commands.describe(ephemeral="true を指定するとエフェメラルで返信します")
    async def health(self, interaction: discord.Interaction, ephemeral: Optional[bool] = None) -> None:
        """Return runtime information about the bot process."""

        ephemeral_flag = await self._resolve_ephemeral(interaction, ephemeral)
        uptime_seconds = time.time() - getattr(self.bot, "started_at", time.time())
        latency_ms = self.bot.latency * 1000
        guild_count = len(self.bot.guilds)
        pid = os.getpid()
        process_memory: Optional[str] = None

        if resource is not None:
            try:
                usage = resource.getrusage(resource.RUSAGE_SELF)
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

        await interaction.response.send_message("\n".join(lines), ephemeral=ephemeral_flag)

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
