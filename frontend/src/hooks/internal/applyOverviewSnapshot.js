// overview SSE の 1 snapshot を現在の loading dict に適用する純粋関数。
// loading (= 停止ボタンの真値) の唯一のソース。 backend 権威 busy をそのまま反映しつつ、
// 送信直後の楽観フラグ (pendingSendRef) を見て busy=false の早すぎる適用だけ確定的に保留する。
//
// pendingSendRef.current[sid] = {seen:boolean} の意味:
//   - busy=true 観測   → ターン開始確認。 フラグ解除、 loading=true (以降 backend 権威)
//   - busy=false 1 回目 → backend がまだ送信を処理してない猶予。 loading=true で保留 (seen=true)
//   - busy=false 2 回目 → ターンが立ち上がらなかった。 フラグ解除、 loading=false (送信ボタンへ)
// pending が無ければ loading[sid] = busy をそのまま適用 (= イベント取りこぼし時も次 snapshot
// で必ず正しい値に収束する reconcile)。
export function applyOverviewSnapshot(prev, payload, pendingSendRef) {
  const next = { ...prev }
  let changed = false
  for (const sid of Object.keys(payload || {})) {
    const busy = !!payload[sid]?.busy
    const pending = pendingSendRef?.current?.[sid]
    let target = busy
    if (pending) {
      if (busy) {
        pendingSendRef.current[sid] = null
        target = true
      } else if (pending.seen) {
        pendingSendRef.current[sid] = null
        target = false
      } else {
        pending.seen = true
        target = true
      }
    }
    if (!!next[sid] !== target) {
      next[sid] = target
      changed = true
    }
  }
  return changed ? next : prev
}
