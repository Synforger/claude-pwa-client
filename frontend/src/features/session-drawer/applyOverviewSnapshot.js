// overview SSE の 1 snapshot を現在の loading dict に適用する純粋関数。
// loading (= 停止ボタンの真値) の唯一のソース。 backend 権威 busy をそのまま反映しつつ、
// 送信/停止 直後の楽観意図 (optimisticRef) を「backend が追いつくまで」 だけ保持する。
//
// optimisticRef.current[sid] = { want: 'busy' | 'idle', startedAt: number }
//   - want='busy' (送信直後): 停止ボタンを出したい。 busy=true 観測でターン開始確認 → 解除。
//     旧仕様は「busy=false が 2 連続観測 → 諦め」 だったが、 これだと claude の立ち上がり
//     遅延 (= text を tmux に送信 → claude が受けて推論開始 → assistant 行を backend が
//     観測するまでの数百ms〜数秒) の間に overview snapshot が 2 回流れて誤諦め → 送信ボタン
//     解禁され「推論中なのに送信できる」 jank を起こしてた (2026-06-04 根治)。 諦めは
//     snapshot 回数でなく **時間ベース**にして、 startedAt から WANT_BUSY_TIMEOUT_MS 経過
//     まで保持する (= claude が assistant 行を出さない no-op turn の安全弁、 通常の立ち
//     上がりはこの猶予内に確実に busy=true を観測する)。
//   - want='idle' (停止直後): 送信ボタンを出したい。 busy=false 観測で停止確定 → 解除。
//     停止は backend が user_stopped → busy=false を **必ず** 返すので、 タイムアウト無しで
//     観測まで保持し続ける (= 1 押下で送信ボタンに戻る、 旧 2 連打バグの根治を維持)。
// optimistic が無ければ loading[sid] = busy をそのまま適用 (= 取りこぼし時も次 snapshot で収束)。
//
// now: 主に test で固定値を渡すための注入口。 通常は Date.now() でリアルタイム。
export const WANT_BUSY_TIMEOUT_MS = 10000

export function applyOverviewSnapshot(prev, payload, optimisticRef, now = Date.now()) {
  const next = { ...prev }
  let changed = false
  for (const sid of Object.keys(payload || {})) {
    const busy = !!payload[sid]?.busy
    const opt = optimisticRef?.current?.[sid]
    let target = busy
    if (opt) {
      const wantBusy = opt.want === 'busy'
      const startedAt = opt.startedAt ?? now  // 移行期 / 旧 opt (startedAt 未設定) は now で代用
      if (busy === wantBusy) {
        // backend が楽観意図に追いついた → 解除、 以降は権威
        optimisticRef.current[sid] = null
        target = busy
      } else if (wantBusy && now - startedAt > WANT_BUSY_TIMEOUT_MS) {
        // 送信のタイムアウト諦め: 立ち上がりが 10 秒以上音沙汰なし = no-op turn か、 PTY 経路で
        // text が届かなかった異常。 権威 (=busy=false) に従って送信ボタンに戻す。
        optimisticRef.current[sid] = null
        target = busy
      } else {
        // 保持。 want='busy' は startedAt から 10s 以内、 want='idle' は無条件。
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
