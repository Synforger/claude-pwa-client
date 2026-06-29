# Claude PWA Client

Claude Code をスマートフォンから操作するための PWA クライアント。 ホストマシン上で動かす
バックエンドに Tailscale 経由で iPhone / Android のブラウザから接続し、 ホーム画面に追加して
スタンドアロン PWA として利用する。

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
- **マルチアカウント**: `accounts` 設定で個人 / 会社等を切り替え (詳細は [docs/config.md](docs/config.md))

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
[docs/architecture.md](docs/architecture.md) を参照。

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

2 段階構成:

- **Path A** (= チャット + 通知のみ): [docs/setup/path-a-chat.md](docs/setup/path-a-chat.md)
- **Path B** (= 上記 + デスクトップ画面共有): [docs/setup/path-b-screenshare.md](docs/setup/path-b-screenshare.md)
- **Windows (WSL2)** の場合: [docs/setup/windows-wsl.md](docs/setup/windows-wsl.md)

ざっくり最短経路 (Path A、 macOS / Linux):

```bash
git clone https://github.com/<your-handle>/claude-pwa-client.git
cd claude-pwa-client

# backend
conda create -n pwa-client python=3.11 && conda activate pwa-client
pip install -r backend/requirements.txt
cp backend/config.example.json backend/config.json   # 編集
python -m backend.cli.gen_vapid                      # backend/secrets/vapid.json 生成
uvicorn backend.main:app --host 0.0.0.0 --port 8765

# frontend
(cd frontend && npm install && npm run build)

# tailnet 公開
tailscale serve --bg http://localhost:8765
```

スマートフォンで `https://<your-host>.tail<xxxx>.ts.net/` を開き、 iOS Safari なら
共有 → ホーム画面に追加で PWA 化。 通知は ⋯ メニュー → 「通知を有効にする」 (iOS 16.4+ +
ホーム画面追加済が必須)。

> **詰まりやすい 2 点** (= 上の最短経路だけだと抜けやすい):
> - **チャットが表示されない** → claude の **hook 設定** (PWA タブと jsonl の紐付け) が必要
> - **ステータスバーが空** → 使用率を記録する **statusline 設定** が必要 (表示専用 statusline では出ない)
>
> どちらも [docs/setup/path-a-chat.md](docs/setup/path-a-chat.md) に手順がある。 加えて
> `claude` を **PATH に通す** + `launch_alias` 対応の **shell alias 定義** + **`jq` / `tmux`**
> が前提。

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
`frontend/.env.local` の詳細は [docs/config.md](docs/config.md) を参照。

## Troubleshooting

代表的なつまずきポイントと復旧手順は [docs/troubleshoot.md](docs/troubleshoot.md) に集約
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
├── frontend/                      # React + Vite
│   ├── src/
│   │   ├── App.jsx                # ルートコンポーネント
│   │   ├── overlays/              # 全画面 / サイドモーダル類
│   │   ├── components/            # ChatInput / StatusBar / Terminal / SubagentsModal 等
│   │   │   ├── MessageRenderer.jsx
│   │   │   └── ErrorBoundary.jsx
│   │   ├── messageRegistry/       # MessageItem の system kind → Render lookup
│   │   ├── SystemMessages/        # system 系メッセージの個別レンダリング
│   │   ├── tools/                 # formatTool の per-tool ハンドラ
│   │   ├── hooks/                 # チャット / SSE / 永続化 hook 群
│   │   └── utils/                 # api / format / favorites / id / storage 等
│   └── public/
│       ├── manifest.template.json # PWA manifest
│       └── sw.js                  # Service Worker (Web Push 受信)
└── docs/                          # 詳細ドキュメント (下記 docs index 参照)
```

## 開発フロー (= ローカルチェックのみ、 GitHub Actions 不使用)

このリポは品質ゲートを全部ローカル `.githooks/` に置く運用。 GitHub Actions の workflow は使わない (= 配信先が個人 / 1 端末で、 PR ごとに remote ランナー回す価値が薄い + 失効した workflow の維持コストを避ける)。 clone 後の活性化:

```bash
git config --local core.hooksPath .githooks
```

これだけで commit 時に以下が staged 範囲に応じて自動で走る:

1. **anon-scan** (= `.tooling/local-ci/anon-scan.sh`): 個人識別子 / 旧雇用主 / ホスト名の混入チェック (全 commit)
2. **flake8** (= staged Python のみ): 構文 / 未定義名 / f-string などの致命チェック
3. **eslint** (= staged JS/JSX/TS/TSX のみ): `frontend/node_modules/eslint` 存在時のみ
4. **audit-w2-residue** (= `.tooling/local-ci/audit-w2-residue.py`): `frontend/src/state/` `features/` `layout/` `*.css` のいずれかが staged の時のみ。 状態二重管理 / orphan setter / CSS absolute anchor の 3 種を機械検出 (= W2 architecture residue 用)

意図的に gate を回避したい時は `--no-verify`。 既知の偽陽性は `.tooling/local-ci/audit-w2-residue-allowlist.txt` に追記。

## docs index

| file | 内容 |
|---|---|
| [docs/setup/path-a-chat.md](docs/setup/path-a-chat.md) | Path A セットアップ (チャット + 通知): 依存 / backend / frontend / Tailscale / LaunchAgent / スマホ接続 |
| [docs/setup/path-b-screenshare.md](docs/setup/path-b-screenshare.md) | Path B 追加セットアップ: Sunshine / moonlight-web-stream ビルド / ペアリング / 音声経路 |
| [docs/setup/windows-wsl.md](docs/setup/windows-wsl.md) | Windows (WSL2) 上での backend / frontend / Tailscale 構成 |
| [docs/config.md](docs/config.md) | `backend/config.json` (`agents` / `accounts` / `claude_path` / `launch_alias` 等) + `frontend/.env.local` 詳細 |
| [docs/troubleshoot.md](docs/troubleshoot.md) | HTTPS 証明書エラー / encoder hang / ペアリング破損 / `__pycache__` 等 |
| [docs/architecture.md](docs/architecture.md) | レイヤ構成と責務分割 (terminal / jsonl / routes / core) |
| [docs/streams.md](docs/streams.md) | SSE / WebSocket ストリームの設計 (`/jsonl/stream`, `/views/ws`, `/ws/pty`) |
| [docs/extending.md](docs/extending.md) | 新規 message kind / tool / system message を追加する手順 |
| [docs/sse-event-shape.md](docs/sse-event-shape.md) | SSE イベントの shape 仕様 |
| [docs/sunshine-runbook.md](docs/sunshine-runbook.md) | Sunshine 運用 runbook |

## ライセンス

Apache License 2.0 (`LICENSE` および `NOTICE` を参照)。

Sunshine / moonlight-web-stream は GPL-3.0 ライセンスだが、 本リポジトリはこれらをバンドル
・ リンクしていない。 別プロセスとして起動し HTTP / WebRTC 経由で連携するため、 本リポジトリ
自体に GPL の copyleft は波及しない (FSF GPL FAQ「プロセス分離は通常 derivative work には
当たらない」に依拠)。

派生物では `NOTICE` を保持し、 改変した主要ファイルにその旨を明記すること (Apache-2.0 §4)。

## 謝辞

- [Claude Code](https://docs.claude.com/en/docs/claude-code) — Anthropic 公式 CLI
- [Sunshine](https://github.com/LizardByte/Sunshine) — 自己ホスト型ゲームストリームサーバ
- [moonlight-web-stream](https://github.com/MrCreativ3001/moonlight-web-stream) — Sunshine をブラウザ WebRTC で受ける bridge
