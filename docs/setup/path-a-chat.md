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
- Claude Code CLI (`claude` コマンド、 認証済み。 **PATH を通しておく** — [§ claude の PATH と起動 alias](#claude-の-path-と起動-alias) 参照)
- `tmux` (backend は claude を実 PTY + tmux で起動するため必須)
- `jq` (ステータスバーの使用率を記録する statusline スクリプトが依存 — [§ ステータスバーを有効にする](#ステータスバー-モデル--使用率-を有効にする) 参照)

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

## claude の PATH と起動 alias

backend は PWA でタブを作る時、 config.json の `launch_alias` に書いた文字列を tmux pane に
送って claude を起動する (詳細は [../config.md](../config.md))。 そのため次の 2 つが揃って
いる必要がある:

1. **`claude` が PATH 上にあること** — 無いと alias も `claude` 単体も `command not found`
   で起動に失敗する。 インストール先 (例: `~/.local/bin`) を `~/.zshrc` 等で PATH に通す:

   ```bash
   export PATH="$HOME/.local/bin:$PATH"
   ```

2. **`launch_alias` に対応する shell alias を定義すること** — `config.json` の各 agent の
   `launch_alias` と同じ名前で、 その agent の cwd に移動して claude を起動する alias を
   `~/.zshrc` 等に置く:

   ```bash
   alias agent_a='cd /path/to/agent_a && claude'
   ```

設定後は新しいシェルを開くか `source ~/.zshrc` で反映する。 既に開いているターミナルや
起動済みの backend には反映されないので注意 (= 既存タブは作り直しが必要)。

## フロントエンド

```bash
cd frontend
npm install
npm run build  # dist/ を生成、 バックエンドが配信
```

## PWA 連携の hook を設定する (チャット表示に必須)

PWA がチャットを表示し通知を出すには、 claude の hook が backend の `/hooks/event` に
「この PWA タブ = この claude セッション (jsonl)」 と通知して紐付け (bind) する必要がある。
**これが無いと、 claude は起動してもターミナル (PTY) 画面にしか出ず、 チャット UI に履歴が
出ない。** セットアップで最も見落としやすい所。

`~/.claude/settings.json` の `hooks` に以下を追加する (既存の hook があれば各 event の配列に
足す)。 port は backend の起動 port に合わせる:

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": "curl -s -o /dev/null -m 2 -X POST http://127.0.0.1:8765/hooks/event -H 'Content-Type: application/json' -H \"X-PWA-SID: ${PWA_SID:-}\" -d @-" } ] }
    ],
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "curl -s -o /dev/null -m 2 -X POST http://127.0.0.1:8765/hooks/event -H 'Content-Type: application/json' -H \"X-PWA-SID: ${PWA_SID:-}\" -d @-" } ] }
    ],
    "Stop": [
      { "hooks": [ { "type": "command", "command": "curl -s -o /dev/null -m 2 -X POST http://127.0.0.1:8765/hooks/event -H 'Content-Type: application/json' -H \"X-PWA-SID: ${PWA_SID:-}\" -d @-" } ] }
    ],
    "Notification": [
      { "hooks": [ { "type": "command", "command": "curl -s -o /dev/null -m 2 -X POST http://127.0.0.1:8765/hooks/event -H 'Content-Type: application/json' -H \"X-PWA-SID: ${PWA_SID:-}\" -d @-" } ] }
    ]
  }
}
```

仕組み:

- backend は PWA タブを起動する時、 tmux session env に `PWA_SID` (= タブ識別子) を注入する。
  hook はそれを `X-PWA-SID` ヘッダに載せて送ることで、 backend が「どのタブの claude か」 を
  確定して jsonl に bind する
- ターミナルから直接起動した claude は `PWA_SID` を持たないので backend 側で無視される (= 無害)。
  同じ settings を全 claude セッションで共有して問題ない
- `SessionStart` だけでも bind は成立する。 `Stop` / `Notification` を足すと turn 完了や
  問い合わせ時に Web Push 通知が飛ぶ。 なお `/hooks/event` は localhost のみ受付

## ステータスバー (モデル / 使用率) を有効にする

PWA 上部のステータスバー (モデル名 / 5h・7d 使用率 / context バー) は、 backend が config.json の
`rate_limits_log` に指定した JSONL を読んで表示する。 **このファイルを書くのは claude の
statusline スクリプト**。 claude は statusline subprocess に使用率等を JSON で渡すので、 それを
1 行ずつ追記する statusline を設定する (表示専用の statusline だと書き込まれず、 ステータスバーが
空のままになる)。

`~/.claude/settings.json`:

```json
"statusLine": { "type": "command", "command": "/path/to/statusline.sh" }
```

`statusline.sh` の backend 連携部分 (= 表示の組み立てに続けて末尾に追記する。 `jq` 必須):

```bash
#!/bin/bash
input=$(cat)

MODEL=$(echo "$input" | jq -r '.model.display_name // "?"')
CTX_PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
FIVE_H=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
FIVE_H_RESET=$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')
WEEK=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')
WEEK_RESET=$(echo "$input" | jq -r '.rate_limits.seven_day.resets_at // empty')
IN_TOKENS=$(echo "$input" | jq -r '.context_window.total_input_tokens // 0')
OUT_TOKENS=$(echo "$input" | jq -r '.context_window.total_output_tokens // 0')
SESSION_ID=$(echo "$input" | jq -r '.session_id // ""')

# (ここで好みのステータスライン文字列を組み立てて echo する — 表示は任意)

# --- backend 連携: rate_limits を JSONL に追記 (config.json の rate_limits_log と同じ path) ---
TRACKER_LOG="/path/to/rate-limits.jsonl"
if [ -n "$FIVE_H" ]; then
    # account を CLAUDE_CONFIG_DIR から導く (~/.claude-work → "work"、 unset → "personal")。
    # backend はこの account_id で個人 / 会社など複数アカウントの使用率を分けて扱う。
    if [ -n "${CLAUDE_CONFIG_DIR:-}" ]; then
        ACCOUNT_ID=$(basename "$CLAUDE_CONFIG_DIR" | sed 's/^\.claude-//' | sed 's/^\.claude$/personal/')
        [ -z "$ACCOUNT_ID" ] && ACCOUNT_ID="personal"
    else
        ACCOUNT_ID="personal"
    fi
    /usr/bin/python3 - "$TRACKER_LOG" "$SESSION_ID" "$ACCOUNT_ID" "$MODEL" \
        "$FIVE_H" "${FIVE_H_RESET:-0}" "${WEEK:-0}" "${WEEK_RESET:-0}" \
        "$IN_TOKENS" "$OUT_TOKENS" "$CTX_PCT" <<'PYEOF' 2>/dev/null
import json, sys, time
log, sid, acct, model, f5, f5r, w7, w7r, intok, outtok, ctx = sys.argv[1:12]
entry = {
    "timestamp": int(time.time()),
    "session_id": sid, "account_id": acct, "model": model,
    "five_hour_pct": float(f5), "five_hour_resets_at": int(f5r),
    "seven_day_pct": float(w7), "seven_day_resets_at": int(w7r),
    "input_tokens": int(intok), "output_tokens": int(outtok), "context_pct": int(ctx),
}
with open(log, "a") as f:
    f.write(json.dumps(entry) + "\n")
PYEOF
fi
```

注意点:

- **`rate_limits_log` と書き込み先 path を一致させる**。 違うと backend は永遠に空ファイルを読む
- **親ディレクトリは事前に作る** (`mkdir -p`)。 スクリプトは作らないので、 無いと append が
  silent fail する
- **`jq` が無いと値が全部 empty になり** (`if [ -n "$FIVE_H" ]` が false)、 記録されず
  ステータスバーが出ない。 移植前に `which jq` で確認する

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
