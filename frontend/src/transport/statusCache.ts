// all-status payload の localStorage write-through cache (= 起動時 hydrate 用)。
//
// 2026-07-13 「上部バーがたまに --- のまま」 根治: 起動〜SSE 接続確立の間、 直前まで
// 表示していた値を捨てて "---" を出さないよう、 直近 payload を write-through し
// useStatus が起動瞬間から前回値で hydrate する (= 本物の snapshot が届いたら上書き、
// 真の初回起動のみ "---")。 鮮度の担保は接続側の責務 (= heartbeat watchdog + fg bump +
// offline chip)。 write は transport/unified.ts の status channel 受信時。

export const LS_STATUS_KEY = 'cpc_last_all_status'

/** 起動時 hydrate 用: 前回 session の最終 all-status payload (= 無ければ {})。 */
export function getCachedAllStatus(): Record<string, unknown> {
  try {
    const raw = localStorage.getItem(LS_STATUS_KEY)
    const parsed = raw ? JSON.parse(raw) : null
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}
