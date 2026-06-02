// overview SSE の 1 snapshot を現在の loading dict に適用する純粋関数。
// loading (= 停止ボタンの真値) の唯一のソース。 backend 権威 busy をそのまま反映しつつ、
// 送信/停止 直後の楽観意図 (optimisticRef) を「backend が追いつくまで」 だけ保持する。
//
// optimisticRef.current[sid] = { want: 'busy' | 'idle', seen: boolean }
//   - want='busy' (送信直後): 停止ボタンを出したい。 busy=true 観測でターン開始確認 → 解除。
//   - want='idle' (停止直後): 送信ボタンを出したい。 busy=false 観測で停止確定 → 解除。
//   どちらも「意図と逆の busy」 が来たら 1 回は猶予 (= backend がまだ送信/停止を処理してない
//   stale snapshot)、 2 回目で諦めて backend 権威に従う。 これで送信も停止も 1 操作で確実に
//   ボタンが切り替わる (= 停止を 2 回押さないと送信に戻らない問題の解消)。
// optimistic が無ければ loading[sid] = busy をそのまま適用 (= 取りこぼし時も次 snapshot で収束)。
export function applyOverviewSnapshot(prev, payload, optimisticRef) {
  const next = { ...prev }
  let changed = false
  for (const sid of Object.keys(payload || {})) {
    const busy = !!payload[sid]?.busy
    const opt = optimisticRef?.current?.[sid]
    let target = busy
    if (opt) {
      const wantBusy = opt.want === 'busy'
      if (busy === wantBusy) {
        // backend が楽観意図に追いついた → 解除、 以降は権威
        optimisticRef.current[sid] = null
        target = busy
      } else if (wantBusy && opt.seen) {
        // 送信のみの諦め: busy=false が 2 連続 = ターンが立ち上がらなかった (= 即終了 / no-op)
        // → 権威に従って送信ボタンへ。 停止 (want:'idle') はここに来ない (下で保持し続ける)。
        optimisticRef.current[sid] = null
        target = busy
      } else {
        // 保持。 停止 (want:'idle') は backend が user_stopped→busy=false を**必ず**返すので、
        // ストリーム中で一瞬まだ busy=true でも諦めず保持し続ける (= 1 押下で送信に戻り、
        // 2 押し必要だった問題の根治)。 Esc も PTY に送ってるので busy=false は確実に来る。
        // 送信 (want:'busy') の 1 回目の busy=false もここで猶予。
        opt.seen = true
        target = wantBusy
      }
    }
    if (!!next[sid] !== target) {
      next[sid] = target
      changed = true
    }
  }
  return changed ? next : prev
}
