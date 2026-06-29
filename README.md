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
[docs/internals/architecture/overview.md](docs/internals/architecture/overview.md) を参照。

## セキュリティモデル

本リポジトリは個人ホスト機を Tailscale tailnet 内に限定公開する前提で設計している。 インターネット公開を想定した認証 / 認可機構は持たない。 「tailnet 内に到達できる主体はホスト機にログインしているのと同等の権限を持つ」 という前提のもと、 以下の境界を最小限守る:

- **`/file` (GET/PUT) は HOME 配下に制限 + 秘密ファイル deny list** (= `backend/routes/files.py::_DENY_RE`、 真値):
  - SSH 関連: `~/.ssh/`、 ファイル名直 `authorized_keys` / `id_rsa` / `id_ed25519` / `id_ecdsa` / `id_dsa` / `known_hosts`
  - クラウド認証: `~/.aws/`、 `~/.gnupg/`、 `~/.docker/`、 `~/.kube/`、 `~/.config/gh/`、 `~/.netrc`
  - シェル init / 履歴: `~/.zshrc` / `~/.zshenv` / `~/.zprofile` / `~/.bashrc` / `~/.bash_profile` / `~/.profile` / `~/.zsh_history` / `~/.bash_history`
  - 拡張子全般: `*.pem` / `*.key` / `*.p12` / `*.pfx`
- **`/hooks/event` は localhost のみ受付**: claude CLI hook は loopback 前提
- **Markdown レンダラの URL は react-markdown 標準 sanitizer 経由**: `javascript:` / `data:` 等の危険スキームをブロック (内部 `cpc-file://` のみ pass-through)
- **Web Push の subscription / VAPID 鍵は `backend/secrets/` / `backend/data/` の JSON に保存** (= gitignored、 詳細は `docs/reference/data-schemas.md`)

WebSocket (`/ws/pty/{sid}`, `/views/ws`, `/jsonl/stream/{sid}`) や `/sessions/*` HTTP は認証なしで tailnet ACL に委ねている。 公開 / multi-tenant 化する場合は別途 middleware 認証が必要。

脆弱性報告 + audit log + threat model 詳細は [SECURITY.md](SECURITY.md) 参照。 2026-06-29 に pip-audit / npm audit / gitleaks 全件実施済 (= dependency CVE は dep bump で全件解消、 git 履歴の private key 1 件は `git filter-repo` + force push で完全削除 + 該当鍵 revoke 済)。

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

## ドキュメント

- 利用者向けガイドの目次: [docs/README.md](docs/README.md)
- セットアップ手順: [docs/setup/path-a-chat.md](docs/setup/path-a-chat.md) (Path A、 macOS / Linux 最短) / [docs/setup/path-b-screenshare.md](docs/setup/path-b-screenshare.md) (画面共有を足す) / [docs/setup/windows-wsl.md](docs/setup/windows-wsl.md) (Windows)
- 困ったとき: [docs/ops/troubleshoot.md](docs/ops/troubleshoot.md)
- 設定リファレンス: [docs/reference/config.md](docs/reference/config.md)

開発に参加したい人向けの内部資料は [docs/internals/](docs/internals/) (= PWA を使うだけなら読む必要はありません)。

## ライセンス

Apache License 2.0 (`LICENSE` / `NOTICE` 参照)。

依存 OSS の license audit (2026-06-29): backend Python deps + frontend npm production deps は全て **permissive** (MIT / BSD / Apache-2.0 / ISC / MPL-2.0 weak copyleft / PSF / CC0-1.0)、 strong copyleft (GPL / AGPL / LGPL / SSPL) はゼロ。 全 dependency の per-package listing + license summary は [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) 参照。

Sunshine / moonlight-web-stream は GPL-3.0 だが、 本リポジトリはこれらをバンドル / リンクせず、 別プロセスとして起動し HTTP / WebRTC 経由で連携するため GPL copyleft は波及しない (= FSF GPL FAQ「プロセス分離は通常 derivative work には当たらない」 に依拠)。 とくに moonlight-web-stream は PWA frontend が `<iframe src="/moonlight/">` で読み込むだけで、 ユーザが個別に build / 別プロセス起動した web server を Tailscale Serve でリバプロするだけ (= 本リポは source / binary を含まない、 iframe は separate document context = aggregation であり derivative work でない)。 端末側 Moonlight client (= iOS / Android / PC native アプリ) は本リポの経路に居ない (= PWA はブラウザ完結で moonlight-web-stream のみ使用)。

派生物では `NOTICE` を保持し、 改変した主要ファイルにその旨を明記すること (Apache-2.0 §4)。 依存追加 / 削除 / version bump 時は `task gen-notices` で `THIRD_PARTY_NOTICES.md` を再生成。

## 謝辞

- [Claude Code](https://docs.claude.com/en/docs/claude-code) — Anthropic 公式 CLI
- [Sunshine](https://github.com/LizardByte/Sunshine) — 自己ホスト型ゲームストリームサーバ
- [moonlight-web-stream](https://github.com/MrCreativ3001/moonlight-web-stream) — Sunshine をブラウザ WebRTC で受ける bridge
