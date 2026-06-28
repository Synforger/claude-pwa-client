#!/usr/bin/env bash
# /debug/healthcheck を叩いて 12 項目 probe 結果を表示する。
#
# 用途:
#   - 運用者 (= 開発者) の手元 PC で backend の全機能生死を 1 発確認
#   - 症状報告時の原因切り分け (= ファイルツリー死亡 / launch_alias 不発 /
#     push 未着 / PTY fd 超過 / vapid 鍵壊れ / etc.)
#
# 環境変数:
#   PORT  = backend port (= default 8765)
#
# 終了コード:
#   0 = 全 12 check pass
#   1 = 1 件以上 fail (= summary.fail >= 1)
#   2 = backend 応答なし (= curl 失敗)

set -u

PORT="${PORT:-8765}"
URL="http://127.0.0.1:${PORT}/debug/healthcheck"

response="$(curl -fsS --max-time 15 "$URL" 2>&1)"
rc=$?
if [[ $rc -ne 0 ]]; then
  echo "ERROR: curl failed (rc=$rc) on $URL" >&2
  echo "$response" >&2
  exit 2
fi

if command -v jq >/dev/null 2>&1; then
  echo "$response" | jq .
  fail="$(echo "$response" | jq -r '.summary.fail // 0')"
else
  echo "$response"
  fail="$(echo "$response" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("summary",{}).get("fail",0))')"
fi

[[ "$fail" -eq 0 ]] && exit 0 || exit 1
