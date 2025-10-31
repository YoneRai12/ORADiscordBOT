# ORA Discord Bot 拡張版

LM Studio や Google OAuth 連携、データセット管理を備えた Slash Command 中心の Discord Bot テンプレートです。Python 3.11 以上と discord.py 2 系を前提に、本番運用で必要になるログ・再接続・ギルド同期・権限チェックも網羅しています。

## 特徴
- **LM Studio(OpenAI 互換 API) 対応 `/chat`** – 既定で `http://127.0.0.1:1234/v1` を利用し、`LLM_MODEL` を差し替えるだけでモデル変更が可能です。
- **Google ログイン連携 `/login`** – `PUBLIC_BASE_URL/auth/discord?state=...` を返し、state は SQLite に保管して CSRF を防止します。
- **プライバシー既定の切替 `/privacy set`** – ユーザーごとにエフェメラル既定を制御し、公開/非公開を柔軟に選択できます。
- **データセット登録 `/dataset add` と一覧 `/dataset list`** – Slash Command の添付ファイル引数を利用し、ORA バックエンドへの転送とローカル保存を両立します。
- **Ngrok / 固定ドメイン両対応の `PUBLIC_BASE_URL`** – Web 側コールバック URL を柔軟に設定できます。
- **SQLite(aiosqlite) でリンク状態と権限を保存** – Discord ユーザーと Google アカウントのひも付け、プライバシー既定、データセットを永続化します。

## 環境変数
| 変数 | 必須 | 例 | 説明 |
| --- | --- | --- | --- |
| `DISCORD_BOT_TOKEN` | ✅ | `xxxx` | Bot アカウントのトークン |
| `DISCORD_APP_ID` | ✅ | `123456789012345678` | アプリケーション ID |
| `ORA_API_BASE_URL` | 任意 | `https://api.example.com` | `/api/link/init` や `/api/datasets/ingest` を呼び出す際に使用 |
| `PUBLIC_BASE_URL` | 任意 | `https://app.example.com` / `https://xxx.ngrok.app` | `/login` が返すフロントエンドの基底 URL |
| `ORA_DEV_GUILD_ID` | 任意 | `123456789012345678` | ギルド限定同期用 ID。未設定時はグローバル同期 |
| `ORA_BOT_DB` | 任意 | `data/ora_bot.db` | SQLite ファイルの保存先 |
| `LOG_LEVEL` | 任意 | `INFO` | Python ログレベル (数値/名称どちらでも指定可) |
| `LLM_BASE_URL` | 任意 | `http://127.0.0.1:1234/v1` | LM Studio など OpenAI 互換エンドポイント |
| `LLM_API_KEY` | 任意 | `lm-studio` | LLM 呼び出し用 API キー |
| `LLM_MODEL` | 任意 | `openai/gpt-oss-20b` | 使用モデル名 |
| `PRIVACY_DEFAULT` | 任意 | `private` | 既定の公開範囲 (`private` or `public`) |

不足している必須変数がある場合は起動時に明確なエラーメッセージを出して終了します。

## セットアップ
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# (任意) LM Studio を OpenAI 互換で起動
# lms server start --port 1234
```

### Bot の起動
```bash
export DISCORD_BOT_TOKEN=...
export DISCORD_APP_ID=...
python -m src.bot
```

### Docker
```bash
docker build -t ora-discord-bot .
docker run --rm \
  -e DISCORD_BOT_TOKEN=$DISCORD_BOT_TOKEN \
  -e DISCORD_APP_ID=$DISCORD_APP_ID \
  [-e PUBLIC_BASE_URL=$PUBLIC_BASE_URL] \
  [-e ORA_API_BASE_URL=$ORA_API_BASE_URL] \
  [-e ORA_DEV_GUILD_ID=$ORA_DEV_GUILD_ID] \
  [-e LOG_LEVEL=DEBUG] \
  [-e LLM_MODEL="openai/gpt-oss-20b"] \
  ora-discord-bot
```

## Slash Commands 一覧
| コマンド | 説明 |
| --- | --- |
| `/ping` | WebSocket レイテンシをエフェメラルで表示 |
| `/say text ephemeral=false` | 管理者のみ。入力文をそのまま返信 (公開/非公開を選択可能) |
| `/link` | ORA API 経由またはダミーでリンクコードを生成 |
| `/health` | PID / 稼働時間 / ギルド数 / ライブラリバージョンなどを表示 |
| `/login` | Google ログイン用の 1 回限りの state 付き URL を発行 |
| `/whoami` | リンク済み Google アカウントと公開設定を確認 |
| `/privacy set mode:<private|public>` | 返信の既定公開範囲を更新 |
| `/chat prompt:<text>` | LM Studio 互換 API からの応答を返す。ユーザーの公開設定に合わせてエフェメラル制御 |
| `/dataset add file:<Attachment> name?:<string>` | 添付ファイルを登録し、ORA API があればアップロード |
| `/dataset list` | 直近のデータセットを最大 10 件表示 |

エフェメラルの扱いは Discord 仕様に合わせ、`interaction.response.defer(..., ephemeral=True)` や `interaction.response.send_message(..., ephemeral=True)` を適切に使っています。

## データベース
- デフォルトでは `ora_bot.db` に SQLite ファイルを作成します。
- `users` テーブルに Discord ユーザー、Google サブ、公開設定を保存。
- `login_states` テーブルで `/login` の state を 900 秒の TTL 付きで保持。
- `datasets` テーブルでアップロードメタデータを管理。

## Web 連携の流れ
1. `/login` を実行すると state 付き URL を返却。
2. フロントエンド (例: `PUBLIC_BASE_URL/auth/discord`) で Google OAuth を実装し、state を照合。
3. 成功後にバックエンドが `Store.upsert_google_sub` を呼び、Discord ユーザーと Google アカウントを関連付けます。

## LM Studio 連携
- OpenAI 互換 API (例: `http://localhost:1234/v1`) に `chat/completions` を POST します。
- モデル名は環境変数 `LLM_MODEL` で切り替え可能です。
- 応答の JSON 構造が想定外の場合はエラーとして通知されます。

## 権限とログ
- Bot 招待時の推奨スコープ: `bot applications.commands`
- 必要権限: `Send Messages`, `Use Slash Commands`
- ログは `LOG_LEVEL` に従って UTC ISO8601 形式で標準出力に出力され、再接続イベントや例外も記録されます。

## 次のステップ
- Web 側で `/auth/discord` を実装し、state 検証と Google OAuth フローを完結させる。
- `Store.consume_login_state` を用いて 1 回限りの state を消費し、`Store.upsert_google_sub` でリンク情報を保存する。
- ORA API の仕様に合わせて `src/utils/link_client.py` や `src/cogs/ora.py` のアップロード処理を拡張する。
