# Sunshine watchdog runbook

> Status: backend-F-33 (2026-06-21) で backend から外出しした、 Sunshine
> プロセスのリーク対策運用手順。 backend は claude 関連 (= chat / jsonl /
> hooks / pty) のみに責務を絞り、 画面共有 daemon の生死管理は別経路で行う。

## 背景

Sunshine (= moonlight host daemon) は画面共有 encoder の中で `phys_footprint`
が単調増加する既知のリークがある。 観測実績:

- 5 日連続稼働で `phys_footprint` 40 GB まで膨張
- リーク分の多くは swap に退避され RSS には出ず、 `footprint(1)` でしか
  捕捉できない
- 配信終了後に `release/streamer` プロセスがゾンビとして残ると、 watchdog 側の
  「配信中なら触らない」 ガードに引っかかり Sunshine が永遠に reap されない

旧 backend は `backend/core/maintenance.py` に
`restart_sunshine_if_bloated` / `_reap_zombie_streamers` を抱えていたが、
backend の責務 (= claude 経路) と無関係 + backend を別マシンに置く運用が
阻害される。 そこで本機構を外出しした。

## 運用方針

watchdog は以下のいずれかで実装する (= 個人運用の機械依存性に応じて選ぶ):

### 方針 A: LaunchAgent + bash スクリプト

`~/Library/LaunchAgents/local.sunshine-watchdog.plist` を作り、 12 時間
ごとに以下スクリプトを叩く:

```bash
#!/usr/bin/env bash
# sunshine-watchdog.sh
set -euo pipefail

# 閾値 (= backend に居た時と同値、 必要に応じて調整)
MAX_FOOTPRINT_BYTES=$((2 * 1024 * 1024 * 1024))   # 2 GB
STREAMER_ZOMBIE_SECONDS=3600                      # 1h

# 1. release/streamer のうち elapsed が閾値超のものを SIGKILL (= ゾンビ reap)
for pid in $(pgrep -f release/streamer || true); do
  elapsed=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d ' ' || true)
  [[ -z "$elapsed" ]] && continue
  if (( elapsed >= STREAMER_ZOMBIE_SECONDS )); then
    kill -9 "$pid" || true
    logger -t sunshine-watchdog "killed zombie streamer pid=$pid elapsed=${elapsed}s"
  fi
done

# 2. 配信中 (= elapsed が短い streamer) があれば Sunshine には触らない
live=false
for pid in $(pgrep -f release/streamer || true); do
  elapsed=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d ' ' || true)
  [[ -z "$elapsed" ]] && continue
  if (( elapsed < STREAMER_ZOMBIE_SECONDS )); then
    live=true
    break
  fi
done
$live && exit 0

# 3. Sunshine の phys_footprint を測って閾値超なら SIGKILL
sun_pid=$(pgrep -x sunshine || true)
[[ -z "$sun_pid" ]] && exit 0

footprint_line=$(footprint "$sun_pid" 2>/dev/null | grep -iE '(phys_)?footprint:' | head -1 || true)
[[ -z "$footprint_line" ]] && exit 0

# `footprint: 40 GB` / `phys_footprint: 40 GB` 両対応で bytes 換算
amount=$(echo "$footprint_line" | sed -E 's/.*footprint:[[:space:]]*([0-9.]+).*/\1/i')
unit=$(echo "$footprint_line" | sed -E 's/.*footprint:[[:space:]]*[0-9.]+[[:space:]]*([KMGT]?B).*/\1/i')
case "$unit" in
  B) mult=1 ;;
  KB|K) mult=1024 ;;
  MB|M) mult=$((1024*1024)) ;;
  GB|G) mult=$((1024*1024*1024)) ;;
  TB|T) mult=$((1024*1024*1024*1024)) ;;
  *) exit 0 ;;
esac
bytes=$(awk -v a="$amount" -v m="$mult" 'BEGIN{printf "%d", a*m}')

if (( bytes > MAX_FOOTPRINT_BYTES )); then
  kill -9 "$sun_pid" || true
  logger -t sunshine-watchdog "restarted bloated sunshine pid=$sun_pid bytes=$bytes"
fi
```

LaunchAgent plist 例:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.sunshine-watchdog</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>/path/to/sunshine-watchdog.sh</string>
  </array>
  <key>StartInterval</key><integer>43200</integer>   <!-- 12h -->
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/tmp/sunshine-watchdog.log</string>
  <key>StandardErrorPath</key><string>/tmp/sunshine-watchdog.err</string>
</dict>
</plist>
```

ロード:

```bash
launchctl load ~/Library/LaunchAgents/local.sunshine-watchdog.plist
```

### 方針 B: 手動運用 (= 配信を頻繁にする時のみ)

LaunchAgent を組まず、 配信を畳むタイミングで以下を手動実行:

```bash
pkill -9 -f release/streamer && launchctl kickstart -k system/org.sunshine
```

ただし LaunchAgent KeepAlive で Sunshine を立てている場合、 `kill -9` 後に
自動 respawn する。 そうでなければ Sunshine を別途立て直すこと。

## なぜ `kill -9` か (= SIGKILL)

`SIGTERM` (= `launchctl kickstart` 経由の graceful shutdown) は
ScreenCaptureKit / VideoToolbox の resource を中途半端に解放し、 respawn 後の
encoder 初期化を hang させる既知の地雷がある。 `SIGKILL` なら OS が resource を
強制 reap するので、 直後の Sunshine 再起動が常に clean に立ち上がる。

## 元 backend 実装の references

ここに統合した旧 backend 実装の git 履歴:

- `backend/core/maintenance.py` の `restart_sunshine_if_bloated()`
  / `_reap_zombie_streamers()` / `_has_live_streamer()` / `_phys_footprint_bytes()`
  / `_pgrep_one()` / `SUNSHINE_FOOTPRINT_MAX_BYTES` / `STREAMER_ZOMBIE_SECONDS`
  / `_FOOTPRINT_RE`
- 2026-06-04 の改修ノート (= 配信中ガードを「streamer 在席」 から
  「elapsed の短い streamer 在席」 に絞った経緯)

詳細ロジックは git history (= `git log -p backend/core/maintenance.py`) を
参照。
