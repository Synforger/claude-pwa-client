// 通知を押して開いた PWA から、 iPhone の app (= repo の shell/) へタブを渡す。
//
// app には iPhone の通知 (= APNs) が届かないので、 通知はホーム画面の PWA が受ける。 この端末で「通知を app で開く」
// をオンにした時だけ、 通知から開いたタブを `claudepwa://open?ses=<sid>` で app へ渡す (= app 側の受け手は
// shell/ios/App/App/AppLinkPlugin.swift)。 PWA からは app が入っているかを知れない (= 入っていない端末で開くと
// iOS が「アドレスが無効」 を出す) ので、 端末ごとの切り替えにしている。
//
// 通知から開く経路は 2 つ (= public/sw.js の notificationclick): PWA が動いている時は `open-session` の知らせ
// (= layout/ChatPanel.jsx)、 閉じていた時は `/?ses=<sid>` の起動 (= session-drawer/useDeepLink.js)。 どちらも
// openFromNotification を呼ぶ。

const ENABLED_KEY = 'cpc.openNotificationsInApp'
const APP_SCHEME = 'claudepwa'

function capacitor() {
  return typeof window !== 'undefined' ? window.Capacitor : null
}

// app の中の画面か (= app の中では渡す先が自分なので、 渡さない)。
export function inNativeApp() {
  return !!capacitor()?.isNativePlatform?.()
}

// 切り替えを出す端末か: iPhone / iPad のホーム画面の PWA だけ (= app は iOS にしか無い)。
export function openInAppAvailable() {
  if (typeof window === 'undefined' || inNativeApp()) return false
  const nav = window.navigator
  const ios = /iPhone|iPad|iPod/.test(nav.userAgent) || (nav.platform === 'MacIntel' && nav.maxTouchPoints > 1)
  const standalone = nav.standalone === true || !!window.matchMedia?.('(display-mode: standalone)').matches
  return ios && standalone
}

export function openInAppEnabled() {
  try { return localStorage.getItem(ENABLED_KEY) === '1' } catch { return false }
}

export function setOpenInAppEnabled(on) {
  try {
    if (on) localStorage.setItem(ENABLED_KEY, '1')
    else localStorage.removeItem(ENABLED_KEY)
  } catch { /* storage 無効環境は無視 */ }
}

export function appLink(sid) {
  return `${APP_SCHEME}://open?ses=${encodeURIComponent(sid)}`
}

// 通知から開いたタブ。 PWA でもそのタブに切り替え (= PWA に戻った時に同じタブが出る)、 オンの端末では app へ渡す。
export function openFromNotification(sid, setActiveId) {
  if (!sid) return
  setActiveId(sid)
  if (openInAppAvailable() && openInAppEnabled()) window.location.href = appLink(sid)
}

// app の中で、 app を開いた URL のタブを受ける (= AppLinkPlugin の openSession)。 受けを外す関数を返す。
export function listenAppLinks(onOpen) {
  const cap = capacitor()
  if (!inNativeApp() || !cap.isPluginAvailable?.('AppLink')) return () => {}
  const handle = cap.Plugins.AppLink.addListener('openSession', ({ sid } = {}) => {
    if (sid) onOpen(sid)
  })
  return () => { Promise.resolve(handle).then((h) => h?.remove?.()).catch(() => {}) }
}
