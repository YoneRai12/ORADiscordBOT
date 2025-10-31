"""ORA-specific commands including login, privacy, chat, search, and dataset handling."""

from __future__ import annotations

import asyncio
import logging
import secrets
import string
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from ..storage import Store
from ..utils.image_tools import classify_image, ocr_image
from ..utils.llm_client import LLMClient
from ..utils.search_client import SearchClient
from ..utils.voice_manager import VoiceManager

logger = logging.getLogger(__name__)


def _nonce(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class ORACog(commands.Cog):
    """ORA-specific commands: login, privacy, chat, datasets, search, and media tools."""

    def __init__(
        self,
        bot: commands.Bot,
        *,
        store: Store,
        llm: LLMClient,
        public_base_url: Optional[str],
        ora_api_base_url: Optional[str],
        privacy_default: str,
        speak_default: int,
        search_client: SearchClient,
        voice_manager: VoiceManager,
    ) -> None:
        self.bot = bot
        self._store = store
        self._llm = llm
        self._public_base_url = public_base_url
        self._ora_api_base_url = ora_api_base_url
        self._privacy_default = privacy_default
        self._speak_default = speak_default
        self._search = search_client
        self._voice_manager = voice_manager
        self._voice_manager.set_hotword_callback(self._handle_hotword)

    async def _ensure_user(self, user: discord.abc.User) -> None:
        await self._store.ensure_user(
            user.id,
            privacy_default=self._privacy_default,
            speak_search_default=self._speak_default,
        )

    async def _resolve_ephemeral(
        self, interaction: discord.Interaction, override: Optional[bool]
    ) -> bool:
        await self._ensure_user(interaction.user)
        if override is not None:
            return override
        privacy = await self._store.get_privacy(interaction.user.id)
        return privacy == "private"

    async def _maybe_speak(
        self,
        member: discord.Member,
        text: str,
        *,
        force: bool = False,
        progress: bool = False,
    ) -> bool:
        if progress:
            enabled = await self._store.get_search_progress_flag(member.id)
            if enabled != 1:
                return False
        elif not force:
            privacy = await self._store.get_privacy(member.id)
            if privacy == "private":
                return False
        if not member.voice or not member.voice.channel:
            return False
        return await self._voice_manager.play_tts(member, text)

    async def _announce_search_progress(
        self, member: Optional[discord.Member], message: str
    ) -> None:
        if member is None:
            return
        await self._maybe_speak(member, message, progress=True)

    async def _handle_hotword(self, member: discord.Member, command_text: str) -> None:
        text = command_text.strip()
        if not text:
            logger.debug("Hotword detected but command empty")
            return

        replacements = [
            "を調べて",
            "調べて",
            "を調べ",
            "検索して",
            "を検索して",
        ]
        query = text
        for token in replacements:
            if token in query:
                query = query.replace(token, " ")
        query = query.replace("を", " ").strip()

        if not query:
            logger.debug("Hotword detected but query empty after cleanup")
            return

        if not self._search.enabled:
            await self._maybe_speak(member, "検索APIが未設定です。", force=True)
            return

        try:
            await self._announce_search_progress(member, "Web検索を開始します")
            results = await self._search.search(query)
        except Exception:
            logger.exception("Hotword search failed")
            await self._announce_search_progress(member, "検索に失敗しました")
            return

        lines = [f"{title} {url}" for title, url in results] or ["結果は見つかりませんでした"]
        message = "\n".join(lines)
        await self._announce_search_progress(member, "検索が完了しました")
        try:
            await member.send(f"[音声トリガー検索]\n{message}")
        except discord.Forbidden:
            logger.warning("Failed to DM search results to %s", member)

    @app_commands.command(name="login", description="Googleアカウント連携用のURLを発行します。")
    @app_commands.describe(ephemeral="true を指定するとエフェメラルで返信します")
    async def login(self, interaction: discord.Interaction, ephemeral: Optional[bool] = None) -> None:
        await self._ensure_user(interaction.user)
        if not self._public_base_url:
            await interaction.response.send_message(
                "PUBLIC_BASE_URL が未設定のためログインURLを発行できません。",
                ephemeral=True,
            )
            return
        ephemeral_flag = await self._resolve_ephemeral(interaction, ephemeral)
        await interaction.response.defer(ephemeral=ephemeral_flag, thinking=True)
        state = _nonce()
        await self._store.start_login_state(state, interaction.user.id, ttl_sec=900)
        url = f"{self._public_base_url}/auth/discord?state={state}"
        await interaction.followup.send(
            "Google ログインの準備ができました。以下のURLから認証を完了してください。\n" + url,
            ephemeral=ephemeral_flag,
        )

    @app_commands.command(name="whoami", description="連携済みアカウント情報を表示します。")
    @app_commands.describe(ephemeral="true を指定するとエフェメラルで返信します")
    async def whoami(self, interaction: discord.Interaction, ephemeral: Optional[bool] = None) -> None:
        await self._ensure_user(interaction.user)
        ephemeral_flag = await self._resolve_ephemeral(interaction, ephemeral)
        google_sub = await self._store.get_google_sub(interaction.user.id)
        privacy = await self._store.get_privacy(interaction.user.id)
        speak_flag = await self._store.get_search_progress_flag(interaction.user.id)
        lines = [
            f"Discord: {interaction.user} (ID: {interaction.user.id})",
            f"Google: {'連携済み' if google_sub else '未連携'}",
            f"既定の公開範囲: {privacy}",
            f"検索進捗読み上げ: {'ON' if speak_flag else 'OFF'}",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=ephemeral_flag)

    privacy_group = app_commands.Group(name="privacy", description="返信の既定公開範囲を設定します")

    @privacy_group.command(name="set", description="返信の既定公開範囲を変更します。")
    @app_commands.describe(
        mode="private は自分のみ / public は全員に表示",
        ephemeral="true を指定するとエフェメラルで返信します",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="private", value="private"),
            app_commands.Choice(name="public", value="public"),
        ]
    )
    async def privacy_set(
        self,
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
        ephemeral: Optional[bool] = None,
    ) -> None:
        await self._ensure_user(interaction.user)
        ephemeral_flag = await self._resolve_ephemeral(interaction, ephemeral)
        await self._store.set_privacy(interaction.user.id, mode.value)
        await interaction.response.send_message(
            f"既定公開範囲を {mode.value} に更新しました。", ephemeral=ephemeral_flag
        )

    @app_commands.command(name="chat", description="LM Studio 経由で応答を生成します。")
    @app_commands.describe(
        prompt="送信する内容",
        ephemeral="true を指定するとエフェメラルで返信します",
    )
    async def chat(
        self, interaction: discord.Interaction, prompt: str, ephemeral: Optional[bool] = None
    ) -> None:
        await self._ensure_user(interaction.user)
        ephemeral_flag = await self._resolve_ephemeral(interaction, ephemeral)
        await interaction.response.defer(ephemeral=ephemeral_flag, thinking=True)
        try:
            content = await self._llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
        except Exception:
            logger.exception("LLM call failed", extra={"user_id": interaction.user.id})
            await interaction.followup.send("LLM 呼び出しに失敗しました。", ephemeral=ephemeral_flag)
            return

        await interaction.followup.send(content, ephemeral=ephemeral_flag)
        if isinstance(interaction.user, discord.Member):
            await self._maybe_speak(interaction.user, content)

    @app_commands.command(name="speak", description="入力したテキストをボイスチャンネルで読み上げます。")
    @app_commands.describe(
        text="読み上げるテキスト",
        ephemeral="true を指定するとエフェメラルで返信します",
    )
    async def speak(
        self, interaction: discord.Interaction, text: str, ephemeral: Optional[bool] = None
    ) -> None:
        await self._ensure_user(interaction.user)
        ephemeral_flag = await self._resolve_ephemeral(interaction, ephemeral)
        if not isinstance(interaction.user, discord.Member) or not interaction.user.voice:
            await interaction.response.send_message(
                "ボイスチャンネルに接続してから実行してください。",
                ephemeral=ephemeral_flag,
            )
            return
        await interaction.response.defer(ephemeral=ephemeral_flag, thinking=True)
        success = await self._voice_manager.play_tts(interaction.user, text)
        if success:
            await interaction.followup.send("読み上げました。", ephemeral=ephemeral_flag)
        else:
            await interaction.followup.send("読み上げに失敗しました。", ephemeral=ephemeral_flag)

    dataset_group = app_commands.Group(name="dataset", description="データセット管理コマンド")

    @dataset_group.command(name="add", description="添付ファイルをデータセットとして登録します。")
    @app_commands.describe(
        file="取り込む添付ファイル",
        name="表示名（省略時はファイル名）",
        ephemeral="true を指定するとエフェメラルで返信します",
    )
    async def dataset_add(
        self,
        interaction: discord.Interaction,
        file: discord.Attachment,
        name: Optional[str] = None,
        ephemeral: Optional[bool] = None,
    ) -> None:
        await self._ensure_user(interaction.user)
        ephemeral_flag = await self._resolve_ephemeral(interaction, ephemeral)
        if file.filename.lower().endswith(".zip"):
            await interaction.response.send_message(
                "セキュリティ上の理由で ZIP ファイルは受け付けません。",
                ephemeral=ephemeral_flag,
            )
            return
        await interaction.response.defer(ephemeral=ephemeral_flag, thinking=True)

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
            except Exception:
                logger.exception("Dataset upload failed", extra={"user_id": interaction.user.id})
                # TODO: 将来的には隔離環境で zipfile 展開しアンチウイルススキャンを実行する

        msg = (
            f"データセット『{title}』を登録しました (ID: {dataset_id}) "
            f"送信先: {'ORA API' if uploaded else 'ローカルメタデータのみ'}"
        )
        await interaction.followup.send(msg, ephemeral=ephemeral_flag)

    @dataset_group.command(name="list", description="登録済みデータセットを表示します。")
    @app_commands.describe(ephemeral="true を指定するとエフェメラルで返信します")
    async def dataset_list(
        self, interaction: discord.Interaction, ephemeral: Optional[bool] = None
    ) -> None:
        await self._ensure_user(interaction.user)
        ephemeral_flag = await self._resolve_ephemeral(interaction, ephemeral)
        datasets = await self._store.list_datasets(interaction.user.id, limit=10)
        if not datasets:
            await interaction.response.send_message(
                "登録済みのデータセットはありません。", ephemeral=ephemeral_flag
            )
            return
        lines = [f"{dataset_id}: {name} {url or ''}" for dataset_id, name, url, _ in datasets]
        await interaction.response.send_message("\n".join(lines), ephemeral=ephemeral_flag)

    search_group = app_commands.Group(name="search", description="Web検索関連コマンド")

    @search_group.command(name="query", description="外部検索APIで Web 検索を実行します。")
    @app_commands.describe(
        query="検索キーワード",
        ephemeral="true を指定するとエフェメラルで返信します",
    )
    async def search_query(
        self, interaction: discord.Interaction, query: str, ephemeral: Optional[bool] = None
    ) -> None:
        await self._ensure_user(interaction.user)
        if not self._search.enabled:
            await interaction.response.send_message(
                "SEARCH_API_KEY が設定されていません。", ephemeral=True
            )
            return
        ephemeral_flag = await self._resolve_ephemeral(interaction, ephemeral)
        await interaction.response.defer(ephemeral=ephemeral_flag, thinking=True)

        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        progress_msg = await interaction.followup.send(
            "Web検索を開始します…", ephemeral=ephemeral_flag
        )
        await self._announce_search_progress(member, "Web検索を開始します")

        await asyncio.sleep(0.3)
        await progress_msg.edit(content="現在Twitterを検索中…")
        await self._announce_search_progress(member, "現在 Twitter を検索中です")

        await asyncio.sleep(0.3)
        await progress_msg.edit(content="ホームページを閲覧中…")
        await self._announce_search_progress(member, "ホームページを閲覧中です")

        try:
            results = await self._search.search(query)
        except Exception:
            logger.exception("Search failed", extra={"user_id": interaction.user.id})
            await progress_msg.edit(content="検索に失敗しました。")
            await self._announce_search_progress(member, "検索に失敗しました")
            return

        await progress_msg.edit(content="検索が完了しました。結果をまとめています…")
        lines = [f"• {title}\n  {url}" for title, url in results]
        message = "\n".join(lines) if lines else "結果は見つかりませんでした。"
        await interaction.followup.send(message, ephemeral=ephemeral_flag)
        await self._announce_search_progress(member, "検索が完了しました")

    @search_group.command(name="notify", description="検索進捗の読み上げを切り替えます。")
    @app_commands.describe(ephemeral="true を指定するとエフェメラルで返信します")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="on", value="on"),
            app_commands.Choice(name="off", value="off"),
        ]
    )
    async def search_notify(
        self,
        interaction: discord.Interaction,
        mode: app_commands.Choice[str],
        ephemeral: Optional[bool] = None,
    ) -> None:
        await self._ensure_user(interaction.user)
        ephemeral_flag = await self._resolve_ephemeral(interaction, ephemeral)
        enabled = mode.value == "on"
        await self._store.set_search_progress_flag(interaction.user.id, enabled)
        state = "ON" if enabled else "OFF"
        await interaction.response.send_message(
            f"検索進捗読み上げを {state} にしました。", ephemeral=ephemeral_flag
        )

    image_group = app_commands.Group(name="image", description="画像解析コマンド")

    @image_group.command(name="classify", description="画像の簡易分類を行います。")
    @app_commands.describe(
        file="分類する画像",
        ephemeral="true を指定するとエフェメラルで返信します",
    )
    async def image_classify(
        self, interaction: discord.Interaction, file: discord.Attachment, ephemeral: Optional[bool] = None
    ) -> None:
        await self._ensure_user(interaction.user)
        ephemeral_flag = await self._resolve_ephemeral(interaction, ephemeral)
        await interaction.response.defer(ephemeral=ephemeral_flag, thinking=True)
        data = await file.read()
        try:
            label = classify_image(data)
        except Exception:
            logger.exception("Image classification failed")
            await interaction.followup.send("画像分類に失敗しました。", ephemeral=ephemeral_flag)
            return
        await interaction.followup.send(label, ephemeral=ephemeral_flag)
        if isinstance(interaction.user, discord.Member):
            await self._maybe_speak(interaction.user, label)

    @image_group.command(name="ocr", description="画像内のテキストを抽出します。")
    @app_commands.describe(
        file="テキスト抽出する画像",
        ephemeral="true を指定するとエフェメラルで返信します",
    )
    async def image_ocr(
        self, interaction: discord.Interaction, file: discord.Attachment, ephemeral: Optional[bool] = None
    ) -> None:
        await self._ensure_user(interaction.user)
        ephemeral_flag = await self._resolve_ephemeral(interaction, ephemeral)
        await interaction.response.defer(ephemeral=ephemeral_flag, thinking=True)
        data = await file.read()
        try:
            text = ocr_image(data)
        except Exception:
            logger.exception("Image OCR failed")
            await interaction.followup.send("OCR に失敗しました。", ephemeral=ephemeral_flag)
            return
        await interaction.followup.send(text, ephemeral=ephemeral_flag)
        if isinstance(interaction.user, discord.Member):
            await self._maybe_speak(interaction.user, text)
