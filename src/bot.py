"""Entry point for the ORA Discord bot."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .cogs.core import CoreCog
from .cogs.ora import ORACog
from .config import Config, ConfigError
from .logging_conf import setup_logging
from .storage import Store
from .utils.link_client import LinkClient
from .utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


class ORABot(commands.Bot):
    """Discord bot implementation for ORA."""

    def __init__(
        self,
        config: Config,
        link_client: LinkClient,
        store: Store,
        llm_client: LLMClient,
        intents: discord.Intents,
    ) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned_or("!"),
            intents=intents,
            application_id=config.app_id,
        )
        self.config = config
        self.link_client = link_client
        self.store = store
        self.llm_client = llm_client
        self.started_at = time.time()

    async def setup_hook(self) -> None:
        await self.add_cog(CoreCog(self, self.link_client))
        await self.add_cog(
            ORACog(
                self,
                store=self.store,
                llm=self.llm_client,
                public_base_url=self.config.public_base_url,
                ora_api_base_url=self.config.ora_api_base_url,
                privacy_default=self.config.privacy_default,
            )
        )
        self.tree.on_error = self.on_app_command_error
        await self._sync_commands()

    async def _sync_commands(self) -> None:
        if self.config.dev_guild_id:
            guild = discord.Object(id=self.config.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info(
                "Synchronized %d commands to guild %s", len(synced), self.config.dev_guild_id
            )
        else:
            synced = await self.tree.sync()
            logger.info("Synchronized %d commands globally", len(synced))

    async def on_ready(self) -> None:
        assert self.user is not None
        logger.info(
            "Logged in as %s (%s); application_id=%s; guilds=%d",
            self.user.name,
            self.user.id,
            self.application_id,
            len(self.guilds),
        )

    async def on_connect(self) -> None:
        logger.info("Connected to Discord gateway.")

    async def on_disconnect(self) -> None:
        logger.warning("Disconnected from Discord gateway. Reconnection will be attempted automatically.")

    async def on_resumed(self) -> None:
        logger.info("Resumed Discord session.")

    async def on_error(self, event_method: str, *args: object, **kwargs: object) -> None:
        logger.exception("Unhandled error in event %s", event_method)

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CheckFailure):
            command_name = interaction.command.qualified_name if interaction.command else "unknown"
            logger.info(
                "Command check failed",
                extra={"command": command_name, "user": str(interaction.user)},
            )
            message = "このコマンドを実行する権限がありません。"
        else:
            logger.exception("Application command error", exc_info=error)
            message = "コマンド実行中にエラーが発生しました。時間を置いて再度お試しください。"

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


def _configure_signals(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            logger.warning("Signal handlers are not supported on this platform.")
            break


async def run_bot() -> None:
    try:
        config = Config.load()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc

    setup_logging(config.log_level)
    logger.info("Starting ORA Discord bot", extra={"app_id": config.app_id})

    intents = discord.Intents.none()
    intents.guilds = True
    intents.voice_states = True

    link_client = LinkClient(config.ora_api_base_url)
    llm_client = LLMClient(config.llm_base_url, config.llm_api_key, config.llm_model)
    store = Store(config.db_path)
    await store.init()

    bot = ORABot(
        config=config,
        link_client=link_client,
        store=store,
        llm_client=llm_client,
        intents=intents,
    )

    stop_event = asyncio.Event()
    _configure_signals(stop_event)

    async with bot:
        bot_task = asyncio.create_task(bot.start(config.token))
        stop_task = asyncio.create_task(stop_event.wait())

        done, pending = await asyncio.wait(
            {bot_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )

        if stop_task in done:
            logger.info("Shutdown signal received. Closing bot...")
            await bot.close()

        if bot_task in done:
            exc: Optional[BaseException] = bot_task.exception()
            if exc:
                logger.exception("Bot stopped due to an error.")
                raise exc
        else:
            await bot.close()
            await bot_task

        for task in pending:
            task.cancel()

        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


def main() -> None:
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Interrupted by user. Exiting.")


if __name__ == "__main__":
    main()
