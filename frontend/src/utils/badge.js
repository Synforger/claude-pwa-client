// アプリバッジ (ホーム画面アイコン右上の未読数) + 通知センター掃除ヘルパ。
// iOS 16.4+ PWA で Badging API + getNotifications が動く。
import { apiFetch } from './api.js'

/** 数値 N をバッジに反映。 0 は clearAppBadge と等価 (iOS では非表示)。 */
export function setBadge(count) {
  try {
    if (typeof navigator === 'undefined') return
    if (count > 0 && navigator.setAppBadge) {
      navigator.setAppBadge(count).catch(() => { /* ignore */ })
    } else if (navigator.clearAppBadge) {
      navigator.clearAppBadge().catch(() => { /* ignore */ })
    } else if (navigator.setAppBadge) {
      navigator.setAppBadge(0).catch(() => { /* ignore */ })
    }
  } catch { /* ignore */ }
}

// clearAllNotifications を 30s 以内連続発火で debounce する (= F-47)。
// visibility 復帰が短時間に連発するケース (= タブ切替の往復) で backend に
// 同じ POST を投げ続けないため。 「最初の呼出は即時走らせ、 その後 30s 以内の
// 呼出は最後の 1 回だけ末尾実行」 する leading + trailing 戦略。
//
//   - 30s 以内連発 → 最後の意図だけ 30s 後に実行
//   - 30s 経過後の呼出 → 即時実行 + 新たに 30s window 開始
//
// state を module-level に持つので test では `__resetClearDebounce()` でクリア。
const CLEAR_DEBOUNCE_MS = 30_000
let lastClearAt = 0
let pendingTimer = null

async function doClear() {
  let remaining = 0
  try {
    if (typeof navigator !== 'undefined' && navigator.serviceWorker) {
      const reg = await navigator.serviceWorker.ready
      if (reg && typeof reg.getNotifications === 'function') {
        const notifs = await reg.getNotifications()
        for (const n of notifs) {
          try { n.close() } catch { /* ignore */ }
        }
      }
    }
  } catch { /* ignore */ }
  try {
    if (typeof navigator !== 'undefined' && navigator.clearAppBadge) {
      await navigator.clearAppBadge().catch(() => { /* ignore */ })
    }
  } catch { /* ignore */ }
  try {
    await apiFetch(`/notifications/sync`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ count: remaining }),
      // sync は idempotent。 backend が一時的に落ちてても 1 回 retry すれば届く想定。
      retry: 1,
    })
  } catch { /* ignore */ }
}

/**
 * 通知センター + アプリバッジ + backend カウンタの 3 点同期掃除。
 *
 * 呼ぶタイミング: PWA 起動時 / visibility=visible 復帰時。
 *
 * 1. SW 経由で `registration.getNotifications()` を全 close (= iOS 通知センターから消す)
 * 2. `navigator.clearAppBadge()` (= ホーム画面アイコンのバッジを 0)
 * 3. POST `/notifications/sync` で backend `unread_count` を残存数 (= 通常 0) に上書き
 *
 * 30s 以内連続発火は最後の 1 回だけに集約 (= F-47)。
 *
 * iOS PWA は通知センターに通知が残ってる間アプリバッジを「未読通知数」 として上書きする
 * 挙動があるので、 通知本体を消さないと clearAppBadge() が効かない。
 */
export function clearAllNotifications() {
  const now = Date.now()
  const elapsed = now - lastClearAt
  if (elapsed >= CLEAR_DEBOUNCE_MS) {
    // 直近 30s 以内に走ってない → 即時実行
    lastClearAt = now
    if (pendingTimer) { clearTimeout(pendingTimer); pendingTimer = null }
    return doClear()
  }
  // 30s 以内 → 末尾実行で集約。 既に pending があれば差し替えない (= 単一末尾)
  if (pendingTimer) return Promise.resolve()
  const wait = CLEAR_DEBOUNCE_MS - elapsed
  pendingTimer = setTimeout(() => {
    pendingTimer = null
    lastClearAt = Date.now()
    doClear()
  }, wait)
  return Promise.resolve()
}

export function __resetClearDebounce() {
  if (pendingTimer) { clearTimeout(pendingTimer); pendingTimer = null }
  lastClearAt = 0
}
