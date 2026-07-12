// /sessions/status/stream SSE singleton (= 全 sid の model / ctx_pct / plan_mode 等 snapshot)。
// features/status-bar/useStatus.js が subscribe する。
// 設計判断: ADR-019 (= 4 SSE endpoint 別 singleton + _sse 共通 factory)。
//
// localStorage 永続 (= 2026-07-13 「上部バーがたまに --- のまま」 根治):
// 旧来は起動〜SSE 接続確立の間、 直前まで表示していた値を全部捨てて "---" を出していた。
// backend 再起動 / bundle 更新の自動リロード / 回線の遅い接続確立と重なると "---" が
// 居座る。 直近 payload を localStorage に write-through し、 useStatus が起動瞬間から
// 前回値で hydrate する (= 本物の snapshot が届いたら上書き。 真の初回起動のみ "---")。
// 鮮度の担保は接続側の責務 (= heartbeat watchdog + fg bump + offline chip)。

import { createSseSubscriber } from './_sse.ts'

const LS_KEY = 'cpc_last_all_status'

/** 起動時 hydrate 用: 前回 session の最終 all-status payload (= 無ければ {})。 */
export function getCachedAllStatus(): Record<string, unknown> {
  try {
    const raw = localStorage.getItem(LS_KEY)
    const parsed = raw ? JSON.parse(raw) : null
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

export const sessionsStatusSse = createSseSubscriber({
  name: 'sessions-status',
  path: '/sessions/status/stream',
  transform: (raw) => {
    // write-through cache (= 失敗は無視、 表示は live 値で続行)。
    try { localStorage.setItem(LS_KEY, JSON.stringify(raw)) } catch { /* quota 等は無視 */ }
    return raw
  },
})
