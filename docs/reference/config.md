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
        "CLAUDE_CONFIG_DIR": "<path-to-your-claude-config-dir>"
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
- `launcher` (任意、 既定 `false`): `launch_alias` が、 最初のメッセージを見てから claude の
  起動の仕方を決める起動ラッパである時に `true` にする (= 例: プロジェクトごとに別の階層で起動する)。
  `true` の時の挙動:
  - 新しい会話 (= タブ作成 / セッション終了の後) では、 最初のメッセージを送るまで何も入力しない。
    送った時点で本文を本人だけが読める一時ファイルに書き、 `<launch_alias> --first-message-file <file>`
    を入力する。 ラッパはファイルを読んで消し、 本文を claude の最初のメッセージとして渡す
    (= `claude "<本文>"`。 打鍵ではなく引数なので複数行も崩れない)
  - 会話の再開 (= backend 再起動跨ぎの自動再開 / フォーク / 別アカウントでの継続) は
    `claude --resume <id>` ではなく `<launch_alias> --resume <id>` を入力する
- `child_agent` (任意): このエージェントのタブが子のタブを立てる時に使うエージェントの key。
  書いていなければ、 子も同じエージェントで立つ。 詳細: [child-sessions.md](child-sessions.md)
- `rollover` (任意): context が決めた割合に届いた会話を締めさせて、 同じタブで新しい会話を起動し直す
  条件。 書いていないエージェントでは何も起きない。 項目と流れは [rollover.md](rollover.md)
- `voice` (任意): エージェントの返事を音声合成の engine で音にするための設定 (= engine の URL と声の番号、
  言い方の印。 人の声を聞き取る engine と、 言い終えを判定する model も足せて、 足すと話すだけで送る会話に
  なる)。 書いていないエージェントは声を持たない。 項目と口は [voice.md](voice.md)

### `accounts` — マルチアカウント

複数の Claude Code アカウントを切り替えて利用する場合に定義する (任意。 未定義なら
`personal` という名前の単一アカウントとして動作)。 個人 / 会社 で別の Pro / Max サブスクリプションを使い分ける、
あるいは別ユーザの認証コンテキストで動かす用途を想定。

- `display_name`: UI に表示するアカウント名
- `env`: claude 起動時の追加環境変数。 代表的なキーは `CLAUDE_CONFIG_DIR`
  (= claude の設定 / 認証ディレクトリを切り替える)。 アカウントごとに別の認証情報を
  分離保持できる

タブ新規作成時にエージェント × アカウントの組み合わせを選択する。 会話一覧の ⋯ メニューから
既存の会話を別アカウントで継続することもできる (= 会話をそのまま引き継いだタブが開く)。

> **想定している使い分け**: 勤務先から支給されたアカウントと自分のアカウント、 のように
> **元々別の主体に属するアカウント**を持っている場合の切り替え。
>
> 1 人が上限を回避する目的で複数の個人サブスクリプションを用意して回す使い方は想定して
> いない。 Anthropic の利用規約に反する恐れがある (= [Usage Policy](https://www.anthropic.com/legal/aup) /
> [Claude Code — Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance))。
> 各アカウントの利用が、 そのアカウントの契約者本人の作業であることを前提とする。

### 置き場 (器の根)

環境変数 `AGENT_PLATFORM_ROOT` を渡すと、 backend は置き場を `<根>/<役割>/claude-pwa-client/` の下に決めます
(渡さない時は従来の置き場のままです)。

| 役割 | 置き場 | 中身 |
|---|---|---|
| `config` | `<根>/config/claude-pwa-client/` | `config.json`、 `favorites.txt` (⭐) |
| `secrets` | `<根>/secrets/claude-pwa-client/` | `vapid.json` |
| `state` | `<根>/state/claude-pwa-client/` | `data/`、 `logs/`、 `notes/`、 `page-store/`、 `uploads/`、 `backups/` |
| `cache` | `<根>/cache/claude-pwa-client/` | `document-cache/` |

`config.json` の `rate_limits_log` を書いていない時の既定は `<根>/state/statusline/rate-limits.jsonl` です。
個別の環境変数 (`CPC_DATA_DIR` / `CPC_LOGS_DIR` / `CPC_CONFIG_PATH` / `CPC_SECRETS_DIR` / `CPC_USER_DIR`) は根より強く、
`config.json` の `uploads_tmp` と `documents.cache_dir` はそれぞれの既定より強くなります。
根を渡した時は、 backend が立てるタブにも同じ値を `AGENT_PLATFORM_ROOT` として渡します。

### 全体オプション

- `claude_path`: `claude` コマンドの絶対パス (`which claude` で確認)。 PTY 起動時の存在
  検証に利用する。 未設定または不正パスの場合は起動を拒否する。 常駐の起動のように PATH が
  通らない環境では明示する
- `uploads_tmp`: 添付ファイルの一時保存先ディレクトリ
- `agent_message_check` (任意): タブどうしの連絡を届ける前に走らせる検査コマンド (= 語のリスト)。
  書き方は [agent-messages.md](agent-messages.md) の「届ける前に検査する」 を参照
- `agent_message_peers` (任意): 連絡を運び合う別の機械の backend (= 名前 → `url` / `address` / `accounts`)。
  書いた時だけ、 宛先 `相手の名前:タブ` で別の機械のタブへ送れる。 詳細: [`agent-messages.md`](agent-messages.md)
- `agent_message_operator_check` (任意): 連絡に人の発話を付けてよいかを決めるコマンド (= 語のリスト)。
  同じ節を参照
- `agent_message_sender_check` (任意): 連絡の封筒に送り主のタブ名を出してよいかを決めるコマンド
  (= 語のリスト)。 同じ節を参照
- `child_sessions_max` (任意): 1 つのタブが同時に持てる子のタブの数 (= 0 以上の整数、 既定 5)。
  詳細: [child-sessions.md](child-sessions.md)
- `rate_limits_log`: 使用率 (5h / 7d / context) を記録する JSONL の path。 **このファイルを
  書くのは claude の statusline スクリプト** (= claude が statusline subprocess に渡す
  `rate_limits` を 1 行ずつ追記する)。 backend はこれを読んでステータスバーに表示する。
  statusline 側の書き込み path と必ず一致させること。 表示専用の statusline だと書き込まれず
  ステータスバーが空になる (設定手順は [../setup/path-a-chat.md](../setup/path-a-chat.md) の
  「ステータスバーを有効にする」 を参照)
- `tmux_session_map_dir`: tmux session 名と PWA session id の対応を保存するディレクトリ
- `vapid_sub`: Web Push の `sub` クレーム (連絡先 mailto:)
- `notification_title`: Web Push 通知のタイトル文字列
- `device_screen` (任意): iPhone の app の画面の配信の仕方。 `interval_s` (= 1 枚を送る間隔の秒、 既定 1)・
  `max_side` (= 長辺の上限の px、 既定 1280)・`quality` (= JPEG の質、 0 より大きく 1 以下、 既定 0.6)。 書いた値だけが
  既定に重なる。 詳細: [device-ops.md](device-ops.md) の「画面の配信」
- `voice_call_gain_db` (任意): iPhone の app の通話の声だけに掛ける大きさ (dB、 既定 0)。 画面の 🔊 のつまみの倍率の
  上に掛かる。 app の通話は画面の声と鳴らし方が違うので、 つまみ 100% で他の app の音と揃わない時に、 画面の声を
  動かさずに通話の声だけを下げる (= 例: `-26` で約 20 分の 1)。 次に掛けた通話から効く
- `documents` (任意): pdf・Office・tif を頁の画像に変えた物の控えの置き場 (`cache_dir`、 既定は
  `~/.claude-pwa-client/document-cache`) と大きさの上限 (`cache_max_mb`、 既定 1024)。 詳細:
  [documents.md](documents.md)
- `page_origin` (任意): この folder の HTML を、 backend とは別の origin の普通のページとして別の port から開く。
  `{"folder": "~/pages", "port": 8775}` の形で書く。 path をタップすると `/file/view` の代わりに
  `<同じ host>:<port>/<folder の中の path>` が開き、 ページが `localStorage` に残した物は次に開いた時も残る
  (= `/file/view` は sandbox でページの origin を毎回作り直すので、 何も残らない)。 folder の中のページは 1 つの origin を
  共有する。 backend の口にもほかの host にも通信できない所は `/file/view` と同じ。 ページが上の画面 (= 枠に嵌めて開いた時の、
  枠の外の画面) を別の頁へ移すこと (= `target="_top"`・`top.location`) は封じる (= 閉じる ✕ で必ず元の画面へ戻れるように)。
  それ以外 (= スクリプト・フォーム・ポップアップ・ダイアログ・ダウンロード) は使える。 backend は `127.0.0.1:<port>` で待ち受けるので、
  Tailscale 越しに使う時は同じ番号を tailnet に出す (= `tailscale serve --bg --https=<port> http://127.0.0.1:<port>`)。
  書き損じた時と port が塞がっている時は起動ログに理由を出し、 その folder も今どおり `/file/view` で開く
  - **保存箱**: `localStorage` はブラウザごと (= 同じ端末でもブラウザと app で別々) なので、 どこで開いても同じ物を
    読ませたいページは、 その port の `/.store/<folder の中のページの path>` へ読み書きする。 ページが fetch できる
    先はここだけ
    - `GET` → 置いた JSON (= まだ無ければ `null`) と、 その `ETag`
    - `PUT` (= `Content-Type: application/json`) → 丸ごと置き換えて `204` と新しい `ETag`。 1 MB まで
    - `PUT` に `If-Match: <読んだ時の ETag>` を付けると、 その間に別の画面が書いていた時は書かずに `412` と今の中身を返す
    - 箱はページ 1 つに 1 つ (= folder の中に在る HTML の path の分だけ)。 中身は backend の利用者の置き場の
      `page-store/` に置く
- `cors_allow_origins`: 通常は `[]` (backend が同一オリジンで frontend を配信するため
  CORS は不要)。 Vite dev server からアクセスする場合は `["http://localhost:5173"]` 等を
  設定する

### `extensions` (任意)

上部バー右端の 🧩 から開く拡張 (= 別アプリを iframe で嵌める口) の一覧。 省略時は拡張なし。

```json
"extensions": [
  { "id": "<id>", "title": "<name>", "icon": "🎛" },
  { "id": "<id>", "title": "<name>", "icon": "📄", "view": "page" }
]
```

- `id`: 英小文字・数字・ハイフンの 32 文字まで (= 先頭はハイフン不可)。 拡張は `/ext/<id>/` に固定で
  載り、 path は config に書かない
- `title` (任意): 未指定なら `id`
- `icon` (任意): 未指定なら 🧩
- `view` (任意): 開き方。 `"band"` (= 未指定の時) はチャットの上の帯、 `"page"` は入力欄の上を全部使う頁

不正な entry (= id の書式違反 / id の重複) はその 1 件だけ捨て、 起動ログに理由を出す。 `view` の
書き損じは拡張を捨てずに帯として載せ、 起動ログに指摘を出す。 拡張の
載せ方は [../setup/extensions.md](../setup/extensions.md)。

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
