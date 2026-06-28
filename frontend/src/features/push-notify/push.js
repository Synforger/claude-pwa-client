// Web Push 通知の登録/解除ヘルパ。
//
// プラットフォーム要件:
//   - iOS Safari: 16.4+ かつ「ホーム画面に追加」した PWA (display:standalone) でのみ動作。
//                 通常タブ (Safari の中) では subscribe しても push が届かない仕様。
//   - macOS / Windows / Linux のデスクトップブラウザ (Safari / Chrome / Edge / Firefox):
//                 通常タブで subscribe 可能、 OS 通知センターに通知される。 standalone 不要。
//   - Android Chrome: 通常タブ + PWA どちらでも動作。

import { apiFetch } from '../../utils/api.js'

const ENABLED_KEY = 'cpc_push_enabled'

export function isPushSupported() {
  if (typeof window === 'undefined') return false
  return (
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  )
}

export function isStandalone() {
  if (typeof window === 'undefined') return false
  if (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) return true
  // iOS Safari fallback
  return !!window.navigator.standalone
}

// iOS / iPadOS の Safari かどうかを判定する。 macOS Safari は touch event を持たないので
// 弾ける。 navigator.standalone は macOS Safari でも定義されることがあって不安定なので使わない。
export function isMobileSafari() {
  if (typeof window === 'undefined') return false
  const ua = window.navigator.userAgent || ''
  if (/iPhone|iPad|iPod/.test(ua)) return true
  // iPadOS 13+ は UA が Macintosh 風になるので touch capability で補強する
  if (/Macintosh/.test(ua) && typeof document !== 'undefined' && 'ontouchend' in document) return true
  return false
}

export function isPushEnabledLocally() {
  try { return localStorage.getItem(ENABLED_KEY) === '1' } catch { return false }
}

function setEnabledFlag(on) {
  try {
    if (on) localStorage.setItem(ENABLED_KEY, '1')
    else localStorage.removeItem(ENABLED_KEY)
  } catch (e) {
    // quota exceed 等で失敗した場合、 次回起動時に「push 未有効」 扱いになる。
    // 観測のため console に残す (= silent ignore より診断容易)。
    console.warn('[push] failed to persist enabled flag:', e)
  }
}

// VAPID 公開鍵 (base64url) → Uint8Array (applicationServerKey 形式)
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  const out = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}

async function getRegistration() {
  if (!('serviceWorker' in navigator)) return null
  return await navigator.serviceWorker.ready
}

export async function enablePush() {
  if (!isPushSupported()) {
    throw new Error('Push 通知に対応していません')
  }
  // standalone 必須は iOS / iPadOS Safari の制約のみ (= 16.4+ でもホーム画面追加した PWA で
  // のみ push 配信)。 macOS Safari / Chrome / Firefox は通常タブで push 受信可、 Sonoma 以降の
  // 「ドックに追加」 (= PWA install) はオプション。 Android Chrome も通常タブ + PWA 両対応。
  // iOS Safari の判定は userAgent + touch capability で行う (= navigator.standalone は
  // macOS Safari でも定義されうるので不安定、 UA + touchend が公式 Apple 推奨パターン)。
  if (isMobileSafari() && !isStandalone()) {
    throw new Error('iOS では「ホーム画面に追加」した PWA でのみ通知を受け取れます')
  }

  const perm = await Notification.requestPermission()
  if (perm !== 'granted') throw new Error('通知が許可されませんでした')

  const keyRes = await apiFetch(`/push/vapid-public-key`)
  if (!keyRes.ok) throw new Error('サーバ側の VAPID 鍵が未設定です')
  const { public_key } = await keyRes.json()
  if (!public_key) throw new Error('VAPID 公開鍵が空です')

  const reg = await getRegistration()
  if (!reg) throw new Error('Service Worker が登録されていません')

  // 既存サブスクリプションがあれば再利用 (鍵変更時のみ作り直し)
  let sub = await reg.pushManager.getSubscription()
  if (sub) {
    // 鍵不一致なら一度解除
    const existingKey = sub.options && sub.options.applicationServerKey
    if (!existingKey || !buffersEqual(existingKey, urlBase64ToUint8Array(public_key))) {
      await sub.unsubscribe().catch(() => {})
      sub = null
    }
  }
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(public_key),
    })
  }

  const res = await apiFetch(`/push/subscribe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(sub.toJSON()),
  })
  if (!res.ok) throw new Error('サーバへのサブスクリプション登録に失敗')

  setEnabledFlag(true)
  return true
}

export async function disablePush() {
  const reg = await getRegistration()
  if (!reg) { setEnabledFlag(false); return }
  const sub = await reg.pushManager.getSubscription()
  if (sub) {
    try {
      await apiFetch(`/push/unsubscribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sub.toJSON()),
      })
    } catch { /* ignore */ }
    await sub.unsubscribe().catch(() => {})
  }
  setEnabledFlag(false)
}

function buffersEqual(a, b) {
  const av = a instanceof ArrayBuffer ? new Uint8Array(a) : a
  const bv = b instanceof ArrayBuffer ? new Uint8Array(b) : b
  if (av.byteLength !== bv.byteLength) return false
  for (let i = 0; i < av.byteLength; i++) if (av[i] !== bv[i]) return false
  return true
}
