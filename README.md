# ORA Discord Bot 拡張版

LM Studio 連携に加えて VOICEVOX による読み上げ、SerpApi Web 検索、画像分類/OCR、音声トリガー (`ORALLM ...`) を備えた Slash Command 中心の Discord Bot テンプレートです。Python 3.11 以上と discord.py 2 系を前提に、本番運用で必要になるログ・再接続・ギルド同期・権限チェックも網羅しています。

## 特徴
- **LM Studio(OpenAI 互換 API) 対応 `/chat`** – 既定で `http://127.0.0.1:1234/v1` を利用し、`LLM_MODEL` を差し替えるだけでモデル変更が可能です。
- **VOICEVOX 読み上げ `/chat` `/speak`** – ずんだもん(デフォルト ID=1)で回答や任意テキストを VC に読み上げます。検索進捗も設定に応じて通知します。
- **Google ログイン連携 `/login`** – `PUBLIC_BASE_URL/auth/discord?state=...` を返し、state は SQLite に保管して CSRF を防止します。
- **プライバシーと読み上げ既定の切替 `/privacy set` `/search notify`** – ユーザーごとにエフェメラル既定と検索進捗読み上げを制御できます。
- **外部検索 `/search query`** – SerpApi 互換 API で Web 検索し、必要に応じて VC で進捗を読み上げます。
- **画像分類・OCR `/image classify` `/image ocr`** – 添付画像を簡易分類し、pytesseract でテキスト抽出も行います。
- **データセット登録 `/dataset add` と一覧 `/dataset list`** – Slash Command の添付ファイル引数を利用し、ORA バックエンドへの転送とローカル保存を両立します (ZIP は安全のため拒否)。
- **音声ホットワード「ORALLM」** – VC でキーワードを検出すると検索を自動実行し、結果を DM と音声で返します。
- **Ngrok / 固定ドメイン両対応の `PUBLIC_BASE_URL`** – Web 側コールバック URL を柔軟に設定できます。
- **SQLite(aiosqlite) 永続化** – Discord ユーザーと Google アカウントのひも付け、プライバシー既定、検索設定、データセットを保存します。

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
| `VOICEVOX_API_URL` | 任意 | `http://localhost:50021` | VOICEVOX エンジンのベース URL |
| `VOICEVOX_SPEAKER_ID` | 任意 | `1` | 使用するスピーカー ID (例: ずんだもん) |
| `SEARCH_API_KEY` | 任意 | `serpapi_key` | SerpApi など互換 API のキー (未設定で検索無効) |
| `SEARCH_ENGINE` | 任意 | `google` | SerpApi に渡すエンジン (例: `google`, `duckduckgo`) |
| `SPEAK_SEARCH_PROGRESS_DEFAULT` | 任意 | `0` | 検索進捗読み上げの既定 (0=OFF, 1=ON) |

不足している必須変数がある場合は起動時に明確なエラーメッセージを出して終了します。

## セットアップ
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# (任意) LM Studio を OpenAI 互換で起動
# lms server start --port 1234

# (任意) VOICEVOX を起動 (例)
# ./run.exe --host 0.0.0.0 --port 50021
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
  [-e VOICEVOX_API_URL=$VOICEVOX_API_URL] \
  [-e SEARCH_API_KEY=$SEARCH_API_KEY] \
  [-e SEARCH_ENGINE=$SEARCH_ENGINE] \
  [-e LOG_LEVEL=DEBUG] \
  [-e LLM_MODEL="openai/gpt-oss-20b"] \
  ora-discord-bot
```

## Slash Commands 一覧
| コマンド | 説明 |
| --- | --- |
| `/ping` | WebSocket レイテンシを表示 (エフェメラルはユーザー設定 or オプション) |
| `/say text ephemeral?` | 管理者のみ。入力文をそのまま返信 |
| `/link` | ORA API 経由またはダミーでリンクコードを生成 |
| `/health` | PID / 稼働時間 / ギルド数 / ライブラリバージョンなどを表示 |
| `/login` | Google ログイン用の 1 回限りの state 付き URL を発行 |
| `/whoami` | リンク済み Google アカウントと公開設定・検索読み上げ設定を確認 |
| `/privacy set` | 返信の既定公開範囲を更新 |
| `/chat prompt` | LM Studio 互換 API からの応答を返し、VC では VOICEVOX で読み上げ |
| `/speak text` | 任意テキストを VC で読み上げ |
| `/dataset add file name?` | 添付ファイルを登録。ZIP はセキュリティ理由で拒否 |
| `/dataset list` | 直近のデータセットを最大 10 件表示 |
| `/search query` | SerpApi 互換 API で Web 検索し、設定に応じて進捗を読み上げ |
| `/search notify enabled:<bool>` | 検索進捗読み上げの ON/OFF を切替 |
| `/image classify file` | 画像の色調・明暗・縦横比を推定 |
| `/image ocr file` | pytesseract で画像内テキストを抽出 |

すべての Slash Command は `ephemeral` オプションを受け付け、未指定時はユーザーのプライバシー設定に基づいてエフェメラルを自動選択します。コマンド実行時には Discord の仕様に従い `interaction.response.defer(..., ephemeral=...)` および `interaction.response.send_message(..., ephemeral=...)` を適切に使っています。

## 音声機能
- ボイスチャンネル参加者が「ORALLM ...」と発話すると、Whisper による音声認識で検索クエリを抽出し `/search query` 相当の処理を実行します。
- `/chat` や `/speak`、検索進捗では VOICEVOX API (`/audio_query` → `/synthesis`) を叩き、生成した WAV を `discord.FFmpegPCMAudio` で再生します。
- `SPEAK_SEARCH_PROGRESS_DEFAULT` と `/search notify` で検索進捗読み上げの既定値と切替が可能です。

## データベース
- デフォルトでは `ora_bot.db` に SQLite ファイルを作成します。
- `users` テーブルに Discord ユーザー、Google サブ、公開設定、検索進捗フラグを保存。
- `login_states` テーブルで `/login` の state を 900 秒の TTL 付きで保持。
- `datasets` テーブルでアップロードメタデータを管理。

## セキュリティ
- `/dataset add` では未知の ZIP によるマルウェアリスクを避けるため ZIP 拡張子を拒否します。安全に解凍する場合は将来的に Docker などの隔離環境で `zipfile` + アンチウイルススキャンを実装してください。
- VOICEVOX や SerpApi が利用できない場合はエラーメッセージを返し、読み上げや検索をスキップします。

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
- 必要権限: `Send Messages`, `Use Slash Commands`, `Connect`, `Speak`
- ログは `LOG_LEVEL` に従って UTC ISO8601 形式で標準出力に出力され、再接続イベントや例外も記録されます。

## 次のステップ
- Web 側で `/auth/discord` を実装し、state 検証と Google OAuth フローを完結させる。
- `Store.consume_login_state` を用いて 1 回限りの state を消費し、`Store.upsert_google_sub` でリンク情報を保存する。
- ORA API の仕様に合わせて `src/utils/link_client.py` や `src/cogs/ora.py` のアップロード処理を拡張する。
- Whisper モデルサイズや VOICEVOX スピーカー ID を用途に合わせて調整し、検索エンジンを追加する。
