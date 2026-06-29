# Claude PWA Client

> **Unofficial third-party client for Claude Code. Not affiliated with Anthropic.**

[Claude Code](https://docs.claude.com/en/docs/claude-code) (Anthropic 公式 CLI) をスマートフォンから操作するための PWA クライアント。 ホストマシン上で動かすバックエンドに Tailscale 経由で iPhone / Android のブラウザから接続し、 ホーム画面に追加してスタンドアロン PWA として利用する。 backend は `claude` CLI を実 PTY + tmux で subprocess 起動するため Anthropic Usage Policy の枠内で動く (= subscription / API key の choice はユーザに委ねる、 token を抽出しない設計)。

## 主な機能

- **チャット**: 複数セッション並走 + タブ切替 + SSE 逐次表示
- **バックグラウンド継続**: 画面を閉じてもホスト側で処理継続、 復帰時に自動再接続して差分受信
- **Web Push 通知**: `AskUserQuestion` 等のプロアクティブ問い合わせを iOS / Android に通知。
  セッションごとに通知モード切替可
- **Proactive 自動配信**: `Monitor` / `cron` / `ScheduleWakeup` 等で agent 自発の turn を即時表示
- **サブエージェント / ワークフロー閲覧**: `Task` / `Workflow` の transcript を専用パネルで閲覧
- **通知センター自動同期**: PWA 復帰時に OS 通知 / バッジ / backend 未読カウンタを同期
- **ファイルプレビュー**: パスをタップして Markdown + 50+ 言語シンタックスハイライト表示
- **ファイルツリー + お気に入り**: ⋯ メニューからツリー閲覧、 ☆ でお気に入り登録 + 1 タップ移動
- **タスクパネル**: 📋 ボタンで `TaskCreate` 由来 task 一覧表示
- **画像 / テキスト添付**: マルチパート送信 + 履歴永続化
- **ステータスバー**: モデル / プランモード / 残予算 / 5h usage / 7d usage / context 使用率
  をリアルタイム表示 + 当セッション言及 PR 一覧チップ
- **会話のフォーク**: 任意メッセージから新タブで分岐、 親 ・ 子をドロワーで階層表示
- **メッセージ履歴永続化**: lz-string で圧縮して localStorage に保存
- **マルチアカウント**: `accounts` 設定で個人 / 会社等を切り替え (詳細は [docs/reference/config.md](docs/reference/config.md))

### 追加機能 (任意セットアップ)

- **デスクトップ画面共有**: [Sunshine](https://github.com/LizardByte/Sunshine) +
  [moonlight-web-stream](https://github.com/MrCreativ3001/moonlight-web-stream) 経由でホスト機
  デスクトップを PWA 内に映してタッチ遠隔操作する。 詳細は
  [docs/setup/path-b-screenshare.md](docs/setup/path-b-screenshare.md)

## アーキテクチャ

```
[スマートフォン]                  [ホスト機]
                                ┌──────────────────────┐
   PWA (Safari/Chrome) ─────┐   │ FastAPI backend      │
       │                    │   │   ├ Claude Code CLI  │
       │                    ├─▶ │   │   subprocess     │
       │                    │   │   └ Web Push (VAPID) │
   ホーム画面追加で             │   │                      │
   standalone 起動           │   │ moonlight-web-stream │ ← 任意
                            │   │   └ Sunshine         │ ← 任意
                            │   └──────────────────────┘
                            │              ↕ Tailscale
                            └──────────────┘
```

- backend はホスト機で常駐し、 `claude` CLI を **実 PTY + tmux** で起動 (SDK / `--print`
  非対話モードは使わない)。 出力は JSONL tail → SSE、 入力は tmux 経由
- 手元の Claude Code サブスクリプション (Pro / Max) でそのまま動作 (API キー / 従量課金不要)
- スマートフォンからは Tailscale 経由でホスト機の HTTPS にアクセス、 インターネット公開はしない

詳細なレイヤ構成と SSE / JSONL / tmux 経路の責務分割は
[docs/architecture/overview.md](docs/architecture/overview.md) を参照。

## セキュリティモデル

本リポジトリは個人ホスト機を Tailscale tailnet 内に限定公開する前提で設計している。
インターネット公開を想定した認証 / 認可機構は持たない。 「tailnet 内に到達できる主体は
ホスト機にログインしているのと同等の権限を持つ」 という前提のもと、 以下の境界を最小限守る:

- **`/file` (GET/PUT) は HOME 配下に制限 + 秘密ファイル deny list**: SSH 鍵
  (`~/.ssh/`, `*.pem`, `id_rsa`)、 クラウド認証情報 (`~/.aws/`, `~/.gnupg/`, `~/.docker/`,
  `~/.kube/`, `~/.config/gh/`)、 シェル初期化ファイル (`~/.zshrc`, `~/.bashrc`)、
  シェル履歴、 `~/.netrc` を読み書き禁止
- **`/hooks/event` は localhost のみ受付**: claude CLI hook は loopback 前提
- **Markdown レンダラの URL は react-markdown 標準 sanitizer 経由**: `javascript:` /
  `data:` 等の危険スキームをブロック (内部 `cpc-file://` のみ pass-through)
- **Web Push の subscription / VAPID 鍵は `backend/` 配下の JSON に保存**

WebSocket (`/ws/pty/{sid}`, `/views/ws`, `/jsonl/stream/{sid}`) や `/sessions/*` HTTP は
認証なしで tailnet ACL に委ねている。 公開 / multi-tenant 化する場合は別途 middleware 認証
が必要。

## セットアップ

利用者向け動線は `task` コマンドに統一済 (= [go-task](https://taskfile.dev) 必須、 macOS は `brew install go-task/tap/go-task`)。 `task --list` で全 task 一覧。

2 段階構成:

- **Path A** (= チャット + 通知のみ): [docs/setup/path-a-chat.md](docs/setup/path-a-chat.md)
- **Path B** (= 上記 + デスクトップ画面共有): [docs/setup/path-b-screenshare.md](docs/setup/path-b-screenshare.md)
- **Windows (WSL2)** の場合: [docs/setup/windows-wsl.md](docs/setup/windows-wsl.md)

### 前提 (= 詰まりやすい 4 点、 task setup の前に潰す)

1. **`claude` CLI を PATH に通す** + agent ごとの **`launch_alias` shell alias** (例: `alias agent_a='cd /path/to/agent_a && claude'`) を `~/.zshrc` 等に定義 (= 詳細は [docs/setup/path-a-chat.md § claude の PATH と起動 alias](docs/setup/path-a-chat.md))
2. **claude hook 設定** = `~/.claude/settings.json` に backend `/hooks/event` POST を仕込まないと chat に履歴が出ない (= [path-a-chat.md § PWA 連携の hook](docs/setup/path-a-chat.md))
3. **statusline 設定** = `rate_limits` を JSONL に追記する statusline でないと StatusBar が空 (= [path-a-chat.md § ステータスバーを有効にする](docs/setup/path-a-chat.md))
4. **`jq` / `tmux`** 必須 + **Tailscale** をホスト + スマホ両方にインストールして同一 tailnet に参加

### 最短経路 (Path A、 macOS / Linux)

```bash
git clone https://github.com/Synforger/claude-pwa-client.git
cd claude-pwa-client

# 1. 全 setup 1 発 (= conda env / pip / npm / config / VAPID / git hooks)
task setup
# → backend/config.json を編集 (= agents / claude_path / accounts)

# 2. frontend ビルド + backend 起動 (foreground、 Ctrl-C で停止)
task build
task run

# 別 shell で tailnet 公開
task tailscale-serve
```

スマートフォンで `https://<your-host>.tail<xxxx>.ts.net/` を開き、 iOS Safari なら共有 → ホーム画面に追加で PWA 化。 通知は ⋯ メニュー → 「通知を有効にする」 (iOS 16.4+ + ホーム画面追加済が必須)。

### 常駐運用 (= LaunchAgent、 macOS 推奨)

```bash
task install-service      # ~/Library/LaunchAgents/<label>.plist を配置 + 編集案内
# plist 内の絶対 path を編集してから:
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.claudepwa.client.plist
task status               # LaunchAgent + port + /debug/healthcheck 12 項目を 1 発確認
```

### PC 再起動後の動線

LaunchAgent KeepAlive で自動起動するはずなので、 まず `task status` で生死確認。 反応無ければ `task restart` で kickstart、 ログは `task logs`。 細かい復旧手順は [docs/ops/troubleshoot.md](docs/ops/troubleshoot.md)。

## 設定ファイル

`backend/config.json` の骨格 (`backend/config.example.json` から複製):

```json
{
  "agents": {
    "agent_a": {
      "cwd": "/path/to/agent_a",
      "model": "Opus",
      "display_name": "Agent A",
      "launch_alias": "agent_a"
    }
  },
  "accounts": {
    "personal": { "display_name": "個人", "env": {} },
    "work": { "display_name": "会社", "env": { "CLAUDE_CONFIG_DIR": "/Users/you/.claude-work" } }
  },
  "claude_path": "/path/to/claude",
  "rate_limits_log": "/path/to/rate-limits.jsonl",
  "notification_title": "Claude",
  "cors_allow_origins": []
}
```

各フィールド (= `agents` / `accounts` / `claude_path` / `launch_alias` 等) と
`frontend/.env.local` の詳細は [docs/reference/config.md](docs/reference/config.md) を参照。

## Troubleshooting

代表的なつまずきポイントと復旧手順は [docs/ops/troubleshoot.md](docs/ops/troubleshoot.md) に集約
(Chromium 系の HTTPS 証明書エラー、 Sunshine encoder hang、 moonlight ペアリング破損、
`__pycache__` import 事故、 PWA bundle 更新の流れ、 セッション終了後の claude_sid 復旧、 等)。

## ディレクトリ構成

```
claude-pwa-client/
├── backend/                       # FastAPI バックエンド (Python)
│   ├── main.py                    # エントリポイント + ルータ集約 + lifespan task
│   ├── state.py                   # プロセス共有状態
│   ├── config.py                  # 設定読み込み + AGENTS 定義
│   ├── paths.py                   # パス解決ヘルパ (HOME 配下制限 / deny list)
│   ├── protocol.py                # 共通プロトコル定義
│   ├── chat_content.py            # 添付ファイル保存 (uploads/tmp)
│   ├── pty_discover.py            # tmux pane 配下の claude プロセス探索
│   ├── cli/                       # スタンドアロン CLI (= gen_vapid 等)
│   ├── terminal/                  # PTY + tmux + control mode 層
│   │   ├── routes.py              # /ws/pty + /pty/{sid}/send
│   │   ├── runner.py              # claude を実 PTY + tmux で起動・駆動
│   │   ├── confirm.py             # 送信確認 (jsonl カウント + wait + 救済再送)
│   │   ├── session_resolver.py    # session 設定の解決 (autoresume / alias)
│   │   └── control_mode.py        # tmux control mode (-CC) プロトコルパーサ
│   ├── jsonl/                     # ~/.claude/projects 監視 + JSONL → イベント変換層
│   │   ├── routes.py              # /jsonl/stream SSE 配信 + 全 session tail loop
│   │   ├── tail.py                # JSONL tail プリミティブ
│   │   ├── events.py              # JSONL 1 行 → chat UI イベント変換
│   │   ├── session_status.py      # busy / agent_status / tasks / pr_links 更新
│   │   ├── notifications.py       # 停止要因の検出と Web Push 配信
│   │   ├── plan_choices.py        # ExitPlanMode の選択肢抽出
│   │   └── watcher.py             # ~/.claude/projects 監視で session ↔ JSONL を紐付け
│   ├── routes/                    # HTTP / WS 各エンドポイント (= chat.py から分割済)
│   │   ├── sessions.py            # /sessions CRUD / fork / restart / history
│   │   ├── overview.py            # /sessions/status/stream + /sessions/overview/stream + /views/ws
│   │   ├── accounts.py            # /accounts (personal / work)
│   │   ├── chat.py                # /stop など旧 chat 残り (shim 化済)
│   │   ├── files.py               # /file, /files/tree, /task-output
│   │   ├── subagents.py           # subagent / workflow 一覧 + 個別 transcript
│   │   └── hooks.py               # /hooks/event (localhost only)
│   ├── core/                      # 横断ヘルパ
│   │   ├── push.py                # Web Push + 通知履歴 + SSE listener
│   │   ├── usage.py               # 使用率 (5h / 7d / ctx) 組み立て
│   │   ├── maintenance.py         # 起動時/定期 GC (tmux/jsonl/log/cache)
│   │   └── fork.py                # 会話フォーク (parentUuid 鎖の lineage 切り出し)
│   ├── tests/                     # pytest
│   ├── config.example.json
│   └── requirements.txt
├── frontend/                      # React + Vite (= W2 architecture、 ADR-026 着地済)
│   ├── src/
│   │   ├── main.jsx               # entry
│   │   ├── App.jsx                # 10 行 shell (= ErrorBoundary + Layout を return するだけ)
│   │   ├── layout/                # 配置層 (= Layout / ChatPanel / TerminalPane / OverlayHost / ErrorBoundary)
│   │   ├── features/              # 19 機能 (= chat / session-drawer / topbar / status-bar / dialogs / app-effects / ask-user-question / attachments / file-preview / file-tree / fork / ios-native / plan-approval / push-notify / screenshare / subagents / tasks / terminal + __contracts__)
│   │   ├── state/                 # 6 store singleton (= ephemeral / sessions / ui / messages / push / persistence) + _store.js factory
│   │   ├── registry/              # 5 registry (= feature / message / overlay / push / stream)
│   │   ├── transport/             # backend 接続 (= SSE / WS singleton)
│   │   ├── domain/                # 純粋 TS layer (= Session / Message / Tool / Event + invariants)
│   │   ├── ports/                 # 型 only interface (= hexagonal 境界)
│   │   ├── shared/                # feature 跨ぎの共有 component (= ConfirmDialog / Modal.css 等)
│   │   ├── hooks/                 # generic DOM utility (= useEscape / useOutsideClick の 2 件のみ)
│   │   ├── contracts/             # codegen 出力 (= events / ws_channels / http_endpoints の .ts/.py)
│   │   ├── tools/                 # tool block 整形 handler (= _registry.js + family file)
│   │   └── utils/                 # api / format / favorites / id / storage 等
│   └── public/
│       ├── manifest.template.json # PWA manifest
│       └── sw.js                  # Service Worker (= Web Push 受信)
├── docs/                          # 詳細ドキュメント (= docs/README.md 参照)
└── Taskfile.yml                   # task コマンド entry (= task --list で全 task)
```

## 開発フロー (= ローカルチェックのみ、 GitHub Actions 不使用)

このリポは品質ゲートを全部ローカル `.githooks/` に置く運用。 GitHub Actions の workflow は使わない (= 配信先が個人 / 1 端末で、 PR ごとに remote ランナー回す価値が薄い + 失効した workflow の維持コストを避ける)。 clone 後の活性化:

```bash
git config --local core.hooksPath .githooks
```

これだけで commit 時に以下が staged 範囲に応じて自動で走る (= 手動で全件回したい時は `task lint` / `task test` / `task anon:scan`):

1. **anon-scan** (= `.tooling/local-ci/anon-scan.sh`): 個人識別子 / 旧雇用主 / ホスト名の混入チェック (全 commit)
2. **flake8** (= staged Python のみ): 構文 / 未定義名 / f-string などの致命チェック
3. **eslint** (= staged JS/JSX/TS/TSX のみ): `frontend/node_modules/eslint` 存在時のみ
4. **audit-w2-residue** (= `.tooling/local-ci/audit-w2-residue.py`): `frontend/src/state/` `features/` `layout/` `*.css` のいずれかが staged の時のみ。 状態二重管理 / orphan setter / CSS absolute anchor の 3 種を機械検出 (= W2 architecture residue 用)

意図的に gate を回避したい時は `--no-verify`。 既知の偽陽性は `.tooling/local-ci/audit-w2-residue-allowlist.txt` に追記。

## ロードマップ

進行中 / 検討中の作業は [ROADMAP.md](ROADMAP.md) 参照。

## docs index

詳細は [docs/README.md](docs/README.md) を参照。 主要 file:

| file | 内容 |
|---|---|
| [docs/setup/path-a-chat.md](docs/setup/path-a-chat.md) | Path A セットアップ (チャット + 通知): 依存 / backend / frontend / Tailscale / LaunchAgent / スマホ接続 |
| [docs/setup/path-b-screenshare.md](docs/setup/path-b-screenshare.md) | Path B 追加セットアップ: Sunshine / moonlight-web-stream ビルド / ペアリング / 音声経路 |
| [docs/setup/windows-wsl.md](docs/setup/windows-wsl.md) | Windows (WSL2) 上での backend / frontend / Tailscale 構成 |
| [docs/reference/config.md](docs/reference/config.md) | `backend/config.json` (`agents` / `accounts` / `claude_path` / `launch_alias` 等) + `frontend/.env.local` 詳細 |
| [docs/reference/data-schemas.md](docs/reference/data-schemas.md) | `backend/data/*.json` + `secrets/vapid.json` の schema + backup 対象範囲 |
| [docs/ops/troubleshoot.md](docs/ops/troubleshoot.md) | HTTPS 証明書エラー / encoder hang / ペアリング破損 / `__pycache__` 等 |
| [docs/ops/sunshine.md](docs/ops/sunshine.md) | Sunshine 運用 runbook (= phys_footprint リーク対策) |
| [docs/architecture/overview.md](docs/architecture/overview.md) | backend / frontend 構成 (= 19 features + 6 store + 5 registry)、 依存方向 DAG、 SessionState + asyncio.Lock |
| [docs/architecture/state-stores.md](docs/architecture/state-stores.md) | frontend 6 store の責務 + どの feature が subscribe するか |
| [docs/architecture/extending.md](docs/architecture/extending.md) | 新規 message kind / tool / system message / overlay / account / push channel を追加する手順 |
| [docs/protocol/streams.md](docs/protocol/streams.md) | 4 SSE + 2 WS の責任分担 + `/jsonl/stream/*` event wire shape |

## ライセンス

Apache License 2.0 (`LICENSE` / `NOTICE` 参照)。

依存 OSS の license audit (2026-06-29): backend Python deps + frontend npm production deps は全て **permissive** (MIT / BSD / Apache-2.0 / ISC / MPL-2.0 weak copyleft / PSF / CC0-1.0)、 strong copyleft (GPL / AGPL / LGPL / SSPL) はゼロ。 全 dependency の per-package listing + license summary は [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) 参照。

Sunshine / moonlight-web-stream は GPL-3.0 だが、 本リポジトリはこれらをバンドル / リンクせず、 別プロセスとして起動し HTTP / WebRTC 経由で連携するため GPL copyleft は波及しない (= FSF GPL FAQ「プロセス分離は通常 derivative work には当たらない」 に依拠)。

派生物では `NOTICE` を保持し、 改変した主要ファイルにその旨を明記すること (Apache-2.0 §4)。 依存追加 / 削除 / version bump 時は `task gen-notices` で `THIRD_PARTY_NOTICES.md` を再生成。

## 謝辞

- [Claude Code](https://docs.claude.com/en/docs/claude-code) — Anthropic 公式 CLI
- [Sunshine](https://github.com/LizardByte/Sunshine) — 自己ホスト型ゲームストリームサーバ
- [moonlight-web-stream](https://github.com/MrCreativ3001/moonlight-web-stream) — Sunshine をブラウザ WebRTC で受ける bridge
