# Windows (WSL2) セットアップ

backend は POSIX 前提の機能 (PTY / tmux / lsof) を利用するため Windows ネイティブでは
動作しない。 Windows で利用する場合は WSL2 (Ubuntu) の中で Linux 版 backend を動かす。
frontend は Windows 側のブラウザから Tailscale 経由でそのままアクセスできる。

[Path A](./path-a-chat.md) の手順を WSL2 用に置き換えたものが以下。 画面共有が必要な
場合は本 file の手順を完了してから [Path B](./path-b-screenshare.md) に進む。

## 1. WSL2 のインストール

PowerShell を管理者で起動:

```powershell
wsl --install -d Ubuntu
```

再起動後に Ubuntu が立ち上がるのでユーザを作成する。

## 2. Ubuntu 内で依存をインストール

macOS 手順と同等、 `brew` の代わりに `apt`:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm tmux git curl
# claude CLI のインストールは公式手順に従う:
# https://docs.claude.com/en/docs/claude-code
```

## 3. リポジトリと backend / frontend のセットアップ

[Path A](./path-a-chat.md) と同手順:

```bash
git clone https://github.com/<your-handle>/claude-pwa-client.git
cd claude-pwa-client
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/config.example.json backend/config.json
# config.json の claude_path は `which claude` の結果と揃える
# 詳細は ../config.md を参照
python -m backend.cli.gen_vapid
(cd frontend && npm install && npm run build)
```

## 4. systemd user service で常駐起動

`~/.config/systemd/user/claudepwa.service`:

```ini
[Unit]
Description=Claude PWA backend

[Service]
WorkingDirectory=%h/claude-pwa-client
ExecStart=/bin/bash -lc 'source .venv/bin/activate && exec uvicorn backend.main:app --host 0.0.0.0 --port 8765'
Restart=always

[Install]
WantedBy=default.target
```

有効化:

```bash
systemctl --user daemon-reload
systemctl --user enable --now claudepwa.service
# Ubuntu シェルを閉じた後も backend を継続させる:
loginctl enable-linger $USER
```

## 5. Tailscale を WSL2 内にインストール

WSL を Linux ホストとして tailnet に参加させる:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo tailscale serve --bg http://localhost:8765
```

これで `https://<wsl-host>.tail<xxxx>.ts.net/` が backend を指す。 Windows 側にも
Tailscale をインストールして同一 tailnet に参加させれば、 Windows のブラウザ・他端末
からも疎通する。

参考: WSL2 のネットワークモードを `mirrored` に設定すれば Windows ホストの Tailscale を
共有することも可能だが、 設定が増えるため WSL 内に直接 Tailscale を入れる構成の方が
簡素かつ安定する。
