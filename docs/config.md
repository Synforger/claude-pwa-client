# 設定ファイル

Claude PWA Client の設定ファイル仕様。 backend / frontend それぞれの設定経路をまとめる。

## `backend/config.json`

雛形は `backend/config.example.json`。 `cp backend/config.example.json backend/config.json`
してから自環境に合わせて編集する。

```json
{
  "agents": {
    "agent_a": {
      "cwd": "/path/to/agent_a",
      "model": "Opus",
      "display_name": "Agent A",
      "launch_alias": "agent_a"
    },
    "agent_b": {
      "cwd": "/path/to/agent_b",
      "model": "Sonnet",
      "display_name": "Agent B",
      "launch_alias": "agent_b"
    }
  },
  "accounts": {
    "personal": {
      "display_name": "個人",
      "env": {}
    },
    "work": {
      "display_name": "会社",
      "env": {
        "CLAUDE_CONFIG_DIR": "/Users/you/.claude-work"
      }
    }
  },
  "claude_path": "/path/to/claude",
  "uploads_tmp": "/path/to/uploads-tmp",
  "rate_limits_log": "/path/to/rate-limits.jsonl",
  "tmux_session_map_dir": "/path/to/tmux-session-map",
  "vapid_sub": "mailto:you@example.com",
  "notification_title": "Notification",
  "cors_allow_origins": []
}
```

### `agents`

複数のエージェント (= 作業ディレクトリ + モデルの組み合わせ) を定義する。 タブ新規作成時に
ここで定義したエントリから選択する。

- `cwd`: エージェントが動作する作業ディレクトリの絶対パス。 ここに置かれた `CLAUDE.md` は
  `claude` 起動時に自動ロードされる
- `model`: 既定モデル (`Opus` / `Sonnet` / `Haiku` 等)
- `display_name` (任意): UI に表示するエージェント名。 未指定時はキー名がそのまま使われる
- `launch_alias` (任意): タブを新規作成した際に tmux pane へ自動入力する文字列。
  `~/.zshrc` 等に `alias agent_a='cd /path/to/agent_a && claude'` のような起動ラッパを
  定義しておくと、 タブを開いた直後に claude TUI まで自動で立ち上がる。 未指定の場合は
  シェルプロンプトで停止し手動入力を待つ。 既存 tmux session への再接続時 (backend
  再起動跨ぎ / タブ切替後) は claude が継続稼働している前提で何も送信しない

### `accounts` — マルチアカウント

複数の Claude Code アカウントを切り替えて利用する場合に定義する (任意。 未定義なら
単一アカウントとして動作)。 個人 / 会社 で別の Pro / Max サブスクリプションを使い分ける、
あるいは別ユーザの認証コンテキストで動かす用途を想定。

- `display_name`: UI に表示するアカウント名
- `env`: claude 起動時の追加環境変数。 代表的なキーは `CLAUDE_CONFIG_DIR`
  (= claude の設定 / 認証ディレクトリを切り替える)。 アカウントごとに別の認証情報を
  分離保持できる

タブ新規作成時にエージェント × アカウントの組み合わせを選択する。

### 全体オプション

- `claude_path`: `claude` コマンドの絶対パス (`which claude` で確認)。 PTY 起動時の存在
  検証に利用する。 未設定または不正パスの場合は起動を拒否する。 conda 等で PATH が
  通らない環境では明示する
- `uploads_tmp`: 添付ファイルの一時保存先ディレクトリ
- `rate_limits_log`: 使用率 (5h / 7d / context) を記録する JSONL の path。 **このファイルを
  書くのは claude の statusline スクリプト** (= claude が statusline subprocess に渡す
  `rate_limits` を 1 行ずつ追記する)。 backend はこれを読んでステータスバーに表示する。
  statusline 側の書き込み path と必ず一致させること。 表示専用の statusline だと書き込まれず
  ステータスバーが空になる (設定手順は [setup/path-a-chat.md](setup/path-a-chat.md) の
  「ステータスバーを有効にする」 を参照)
- `tmux_session_map_dir`: tmux session 名と PWA session id の対応を保存するディレクトリ
- `vapid_sub`: Web Push の `sub` クレーム (連絡先 mailto:)
- `notification_title`: Web Push 通知のタイトル文字列
- `cors_allow_origins`: 通常は `[]` (backend が同一オリジンで frontend を配信するため
  CORS は不要)。 Vite dev server からアクセスする場合は `["http://localhost:5173"]` 等を
  設定する

## VAPID 鍵 (`backend/secrets/vapid.json`)

Web Push 通知用の鍵ペア。 1 度だけ生成する:

```bash
python -m backend.cli.gen_vapid
```

`backend/secrets/vapid.json` に書き出される (gitignore 済み)。 既存ファイルを上書きする
には `--force` を付ける。 出力には pywebpush に渡す PEM 形式の private key と、 フロントの
`applicationServerKey` 用 base64url エンコード済 public key が含まれる。

## `frontend/.env` / `frontend/.env.local`

- **`frontend/.env`**: リポジトリにコミットされる既定値 (アプリ名 / アイコン等)
- **`frontend/.env.local`**: gitignore 済の個人用オーバーライド。 例:

```
VITE_API_BASE=https://<your-host>.tail<xxxx>.ts.net
```

`VITE_API_BASE` が未設定の場合は同一オリジンの相対 URL になる (backend が frontend を
配信する標準構成では設定不要)。 backend と frontend を別オリジンで運用する場合のみ
明示的に設定する。
