"""Extended ORA-specific slash commands."""

from __future__ import annotations

import logging
import secrets
import string
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.abc import User
from discord.ext import commands

from ..storage import Store
from ..utils.llm_client import LLMClient

logger = logging.getLogger(__name__)


def _nonce(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class ORACog(commands.Cog):
    """ORA-specific commands such as login link and dataset management."""

    def __init__(
        self,
        bot: commands.Bot,
        store: Store,
        llm: LLMClient,
        public_base_url: Optional[str],
        ora_api_base_url: Optional[str],
        privacy_default: str,
    ) -> None:
        self.bot = bot
        self._store = store
        self._llm = llm
        self._public_base_url = public_base_url
        self._ora_api_base_url = ora_api_base_url
        self._privacy_default = privacy_default

    async def _ephemeral_for(self, user: User) -> bool:
        privacy = await self._store.get_privacy(user.id)
        return privacy == "private"

    @app_commands.command(name="login", description="Googleアカウント連携用のURLを発行します。")
    async def login(self, interaction: discord.Interaction) -> None:
        await self._store.ensure_user(interaction.user.id, self._privacy_default)
        if not self._public_base_url:
            await interaction.response.send_message(
                "PUBLIC_BASE_URL が未設定のためログインURLを発行できません。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        state = _nonce()
        await self._store.start_login_state(state, interaction.user.id, ttl_sec=900)
        url = f"{self._public_base_url}/auth/discord?state={state}"
        await interaction.followup.send(
            "Google ログインの準備ができました。以下のURLから認証を完了してください。\n" + url,
            ephemeral=True,
        )

    @app_commands.command(name="whoami", description="連携済みアカウント情報を表示します。")
    async def whoami(self, interaction: discord.Interaction) -> None:
        await self._store.ensure_user(interaction.user.id, self._privacy_default)
        google_sub = await self._store.get_google_sub(interaction.user.id)
        privacy = await self._store.get_privacy(interaction.user.id)
        lines = [
            f"Discord: {interaction.user} (ID: {interaction.user.id})",
            f"Google: {'連携済み' if google_sub else '未連携'}",
            f"既定の公開範囲: {privacy}",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    privacy_group = app_commands.Group(
        name="privacy", description="返信の既定公開範囲を設定します"
    )

    @privacy_group.command(name="set", description="返信の既定公開範囲を変更します。")
    @app_commands.describe(mode="private は自分のみ / public は全員に表示")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="private", value="private"),
            app_commands.Choice(name="public", value="public"),
        ]
    )
    async def privacy_set(
        self, interaction: discord.Interaction, mode: app_commands.Choice[str]
    ) -> None:
        await self._store.ensure_user(interaction.user.id, self._privacy_default)
        await self._store.set_privacy(interaction.user.id, mode.value)
        await interaction.response.send_message(
            f"既定公開範囲を {mode.value} に更新しました。", ephemeral=True
        )

    @app_commands.command(name="chat", description="LM Studio 経由で応答を生成します。")
    @app_commands.describe(prompt="送信する内容")
    async def chat(self, interaction: discord.Interaction, prompt: str) -> None:
        await self._store.ensure_user(interaction.user.id, self._privacy_default)
        ephemeral = await self._ephemeral_for(interaction.user)
        await interaction.response.defer(ephemeral=ephemeral, thinking=True)
        try:
            content = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
        except Exception:
            logger.exception("LLM call failed", extra={"user_id": interaction.user.id})
            await interaction.followup.send("LLM 呼び出しに失敗しました。", ephemeral=True)
            return
        await interaction.followup.send(content, ephemeral=ephemeral)

    dataset_group = app_commands.Group(name="dataset", description="データセット管理コマンド")

    @dataset_group.command(name="add", description="添付ファイルをデータセットとして登録します。")
    @app_commands.describe(
        file="取り込む添付ファイル",
        name="表示名（省略時はファイル名）",
    )
    async def dataset_add(
        self,
        interaction: discord.Interaction,
        file: discord.Attachment,
        name: Optional[str] = None,
    ) -> None:
        await self._store.ensure_user(interaction.user.id, self._privacy_default)
        ephemeral = await self._ephemeral_for(interaction.user)
        await interaction.response.defer(ephemeral=ephemeral, thinking=True)

        title = name or file.filename
        dataset_id = await self._store.add_dataset(interaction.user.id, title, file.url)

        uploaded = False
        if self._ora_api_base_url:
            try:
                timeout = aiohttp.ClientTimeout(total=120)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(file.url) as resp:
                        if resp.status != 200:
                            raise RuntimeError(f"Failed to download attachment: {resp.status}")
                        data = await resp.read()
                    upload_url = f"{self._ora_api_base_url}/api/datasets/ingest"
                    form = aiohttp.FormData()
                    form.add_field("discord_user_id", str(interaction.user.id))
                    form.add_field("dataset_name", title)
                    form.add_field(
                        "file",
                        data,
                        filename=file.filename,
                        content_type=file.content_type or "application/octet-stream",
                    )
                    async with session.post(upload_url, data=form) as response:
                        if response.status == 200:
                            uploaded = True
                        else:
                            body = await response.text()
                            raise RuntimeError(
                                f"Dataset upload failed with status {response.status}: {body}"
                            )
            except Exception:
                logger.exception("Dataset upload failed", extra={"user_id": interaction.user.id})

        msg = (
            f"データセット『{title}』を登録しました (ID: {dataset_id}) "
            f"送信先: {'ORA API' if uploaded else 'ローカルメタデータのみ'}"
        )
        await interaction.followup.send(msg, ephemeral=ephemeral)

    @dataset_group.command(name="list", description="登録済みデータセットを表示します。")
    async def dataset_list(self, interaction: discord.Interaction) -> None:
        await self._store.ensure_user(interaction.user.id, self._privacy_default)
        ephemeral = await self._ephemeral_for(interaction.user)
        datasets = await self._store.list_datasets(interaction.user.id, limit=10)
        if not datasets:
            await interaction.response.send_message(
                "登録済みのデータセットはありません。", ephemeral=ephemeral
            )
            return

        lines = [
            f"{dataset_id}: {name} {url or ''}" for dataset_id, name, url, _ in datasets
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=ephemeral)
