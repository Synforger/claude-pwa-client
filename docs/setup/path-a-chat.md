# Path A: チャット + 通知 セットアップ

最小構成 (= チャット + Web Push 通知のみ)。 画面共有が不要であればこの Path A だけで
完結する。 画面共有まで欲しい場合は本 file の手順を完了してから
[Path B: デスクトップ画面共有](./path-b-screenshare.md) に進む。 Windows ホストの場合は
代わりに [Windows (WSL2) セットアップ](./windows-wsl.md) を参照。

## 必要なもの

- ホスト機 (macOS / Linux。 Windows の場合は WSL2 経由)
- Python 3.11+ (conda 推奨)
- Node.js (フロントエンドビルド用)
- Tailscale (ホスト機とスマートフォン両方にインストールし、 同一 tailnet に参加させる)
- Claude Code CLI (`claude` コマンド、 認証済み)

## バックエンド

```bash
git clone https://github.com/<your-handle>/claude-pwa-client.git
cd claude-pwa-client

# Python 環境
conda create -n pwa-client python=3.11
conda activate pwa-client
pip install -r backend/requirements.txt

# 設定ファイル
cp backend/config.example.json backend/config.json
# config.json を編集してエージェントの cwd / claude コマンドパス等を設定
# 詳細は ../config.md を参照

# Web Push 用の VAPID 鍵生成 (1 度だけ)
python -m backend.cli.gen_vapid  # backend/secrets/vapid.json を生成

# 起動
uvicorn backend.main:app --host 0.0.0.0 --port 8765
```

> **開発時の注意**: backend のサブパッケージ構成や import 構造を変更した時は、
> 古い `__pycache__/*.pyc` が import 事故 (= 旧名 module が残って ImportError)
> の温床になる。 再起動前に下記で purge する:
>
> ```bash
> find backend -name __pycache__ -type d -exec rm -rf {} +
> ```
>
> その他のトラブルは [../troubleshoot.md](../troubleshoot.md) を参照。

## フロントエンド

```bash
cd frontend
npm install
npm run build  # dist/ を生成、 バックエンドが配信
```

## Tailscale で tailnet 内に公開

```bash
# backend を tailnet 経由で HTTPS 提供 (同一オリジンで /)
tailscale serve --bg http://localhost:8765
```

これで `https://<your-host>.tail<xxxx>.ts.net/` が backend を指す。 `tailscale serve status`
で接続状態を確認できる。

> Chromium 系ブラウザで HTTPS 証明書エラーが出る場合は
> [../troubleshoot.md](../troubleshoot.md) の Tailscale 証明書 section を参照。

## backend を常駐起動する (macOS LaunchAgent)

`uvicorn` を毎回手動起動する代わりに、 macOS なら LaunchAgent で常駐させる。
`~/Library/LaunchAgents/com.example.claudepwa.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.example.claudepwa</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>cd /path/to/claude-pwa-client && source /path/to/miniforge/etc/profile.d/conda.sh && conda activate pwa-client && exec uvicorn backend.main:app --host 0.0.0.0 --port 8765</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/path/to/claude-pwa-client/logs/backend.out</string>
  <key>StandardErrorPath</key><string>/path/to/claude-pwa-client/logs/backend.err</string>
</dict>
</plist>
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.claudepwa.plist
```

backend はアプリ内で `RotatingFileHandler` を構成しているため、 上記の `StandardOutPath`
は `uvicorn` 起動行および致命例外を拾う補助用。 メインログは `logs/backend.access.log` /
`logs/backend.error.log` に 5 MB × 3 世代で自動ローテートされる。

Linux では systemd user service で同等の常駐構成を取れる。 Windows は
[windows-wsl.md](./windows-wsl.md) を参照。

## スマートフォンから接続

1. Tailscale でホスト機の MagicDNS 名を確認する (例: `your-host.tail<xxxx>.ts.net`)
2. スマートフォンで `https://<your-host>.tail<xxxx>.ts.net/` を開く
3. iOS Safari の場合は 共有 → ホーム画面に追加 で PWA 化する
4. 通知を有効化する場合は ⋯ メニューの「通知を有効にする」を選択する
   (iOS 16.4+ かつホーム画面追加済みであることが必須)
