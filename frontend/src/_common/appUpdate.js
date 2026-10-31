// 開いたままの画面を、 新しく載った build へ移す。
//
// 新しい build が載ると sw.js の中身が変わる (= アプリシェルの cache 名が build ごとに決まる)。
// ブラウザが sw.js の更新を自分で確かめるのは頁の遷移の時なので、 開いたまま裏へ回っていた
// PWA は、 前面へ戻っても確かめに行かない (= 載せ替えた後も古い画面のまま動き続ける。 古い画面は
// 消えた chunk を読みに行って、 後から読み込む部品から先に効かなくなる)。
//
// ここで確かめる機会を足す:
//   - 画面が起動した時 (= 何かの理由で古い入口の頁から起動しても、 そのまま動き続けない)
//   - 前面へ戻った時 / ブラウザが保存していた頁を戻した時 (= transport/lifecycle.ts の cpc:fg)
//   - backend との接続が開いた時 (= transport/unified.ts の cpc:connected。 圏外で service worker の控えの入口の
//     頁から起動した画面は、 起動の時には確かめられず、 通信が戻ったここで確かめられる)
//   - 開いている間は一定の間隔
// 確かめ方は 2 つで、 どちらが先に気づいても移るのは 1 回:
//   - 入口の頁を取り直し、 そこに載っている build が今動かしている build と違えば移る。 どの入れ物でも
//     行う。 service worker の入れ替えは、 画面がそれを受け取れる時にしか効かない: iPhone の app の
//     WKWebView には service worker の口が無く (= App-Bound Domains を宣言する app にだけ在る)、
//     ホーム画面の PWA も、 build が何度も入れ替わった後に木の一覧の無い古い画面のまま動いていた
//   - service worker が在る時は、 加えて新しい版を探させ、 新しい service worker が有効になったら移る
// 移る時は 1 回だけ読み込み直して新しい build の画面へ移る。
// 会話は保存済みで、 打ちかけの入力は頁を離れる時に保存される (= features/chat/useChatStorage.js)
// ので、 読み込み直しでは消えない。 消えるのは、 選んだだけでまだ送っていない添付 (= 選び直しになる)。
// それが在る間は移るのを見送り、 無くなった時 (= 送った / 外した) に移る。 見送っている間も画面は
// 動き続ける (= 1 つ前の build の部品は配られたまま。 build/publishDist.js)。
import { httpClient } from '../transport/http.ts'

// 開いている間に確かめる間隔。 agent platform の更新の常駐が新しい build を載せる周期と同じ (= 前面に出し
// たままの画面が、 新しい build に長く置いて行かれない)。 取り直す入口の頁は 1 KB ほど。
export const UPDATE_CHECK_INTERVAL_MS = 10 * 60 * 1000

// 入口の頁を取り直して移った build と時刻を、 頁を跨いで覚えておく鍵。 読み込み直した後もまだ違う
// build が配られている (= 入口の頁がどこかで古いまま残っている) 時に、 読み込み直しを繰り返さない。
const RELOADED_TO_KEY = 'cpc_update_reloaded_to'

// 同じ build へ移り直すまで空ける時間。 無期限に見送ると、 移った後に古い頁へ戻された画面が次の build まで
// 古いまま動き続ける。
export const RELOAD_RETRY_MS = UPDATE_CHECK_INTERVAL_MS

// 接続が開いた時に確かめるのを見送る間隔。 前面へ戻る時は接続も張り直すので、 同じ確かめが続けて走る。
export const CONNECTED_CHECK_GAP_MS = 5_000

// この画面が動かしている build (= 読み込んだ入口の script の、 中身から決まる名前の部分)。
export function runningBuildId(doc = document) {
  const entry = doc.querySelector('script[type="module"][src*="/assets/index-"]')
  const match = entry && /\/assets\/index-(.+)\.js$/.exec(entry.getAttribute('src') || '')
  return match ? match[1] : null
}

// service worker に、 新しい版が出ていないかを確かめさせる。
export function checkForUpdate(nav = navigator) {
  if (!nav.serviceWorker) return Promise.resolve()
  return Promise.resolve(nav.serviceWorker.getRegistration())
    .then(reg => (reg ? reg.update() : undefined))
    .catch(() => { /* 圏外など。 次の機会に確かめる */ })
}

// backend が今配っている build (= 入口の頁を取り直して読む。 入口の頁は no-store で配られるので、
// 取るたびに backend から取る。 backend/_internal/static_files.py)。 取れない時は null。
export function fetchServedBuildId(http = httpClient) {
  return Promise.resolve()
    .then(() => http.apiFetch('/'))
    .then(res => (res.ok ? res.text() : null))
    .then(html => (html ? runningBuildId(new DOMParser().parseFromString(html, 'text/html')) : null))
    .catch(() => null)
}

// 直後に読み込み直すので、 頁を離れても送り切る
function report(payload) {
  httpClient.apiFetch('/log/sw', { method: 'POST', jsonBody: payload, keepalive: true }).catch(() => {})
}

// 移り直すのを見送っている build (= 移ってから RELOAD_RETRY_MS 経っていない物)。 無ければ null。
function reloadedToRecently(win) {
  try {
    const { build, at } = JSON.parse(win.sessionStorage.getItem(RELOADED_TO_KEY))
    return Date.now() - at < RELOAD_RETRY_MS ? build : null
  } catch {
    return null
  }
}

// 移った build を覚える。 覚えられたか (= private mode 等では覚えられない) を返す。
function saveReloadedTo(win, build) {
  try {
    win.sessionStorage.setItem(RELOADED_TO_KEY, JSON.stringify({ build, at: Date.now() }))
    return true
  } catch {
    return false
  }
}

// この画面の入れ物 (= 古い build の報告を、 どの入れ物で起きたかで見分ける)。
function containerOf(win) {
  if (win.Capacitor?.isNativePlatform?.()) return 'app'
  return win.matchMedia?.('(display-mode: standalone)')?.matches ? 'home-screen' : 'browser'
}

// この頁をどう読み込んだか (= 再読込・戻る・新規と、 通信で届いた量。 0 なら手元の控え)。
function navigationOf(win) {
  const [entry] = win.performance?.getEntriesByType?.('navigation') || []
  return entry ? { navigation: entry.type, transferSize: entry.transferSize } : {}
}

let installed = false

// unsent = 読み込み直すと消える、 ユーザの手元の物 (= 未送信の添付と、 画面の中の声の会話) の見張り:
//   { hasAny: () => boolean, subscribe: (listener) => unsubscribe }
// 渡さなければ、 見送らずにすぐ移る。
// http = 入口の頁を取り直す口。 send = backend の記録 (= `sw-log`) へ 1 行送る口。 起動した版 (= `update:boot`)、
// 移る時 (= `update:reload`)、 違う build が配られているのに移り直せない時 (= `update:held`) に送る。
export function installUpdateChecks({
  win = window, doc = document, nav = navigator, unsent = null, http = httpClient, send = report,
} = {}) {
  if (installed) return
  installed = true

  let reloading = false
  let waiting = false
  const reload = () => {
    if (reloading) return
    reloading = true
    win.location.reload()
  }
  // 手元の物が無ければすぐ、 在れば無くなった知らせで 1 回だけ移る
  const reloadWhenFree = (beforeReload = null) => {
    if (reloading || waiting) return
    const go = () => { if (beforeReload) beforeReload(); reload() }
    if (!unsent || !unsent.hasAny()) { go(); return }
    waiting = true
    const stop = unsent.subscribe(() => {
      if (unsent.hasAny()) return
      stop()
      go()
    })
  }

  const hasServiceWorker = !!nav.serviceWorker
  if (hasServiceWorker) {
    // 新しい service worker が有効になった = 新しい build が載った。
    // 初めて登録された時 (= 管理する service worker が無かった頁に付いた時) は更新ではないので数えない。
    let controlled = !!nav.serviceWorker.controller
    nav.serviceWorker.addEventListener('controllerchange', () => {
      if (!controlled) { controlled = true; return }
      reloadWhenFree()
    })
  }

  // 入口の script を持たない頁 (= 開発の server) は、 比べる build が無い
  const running = runningBuildId(doc)
  let servedCheckedAt = -Infinity
  const checkServedBuild = ({ booted = false } = {}) => {
    if (!running) return
    servedCheckedAt = Date.now()
    fetchServedBuildId(http).then(served => {
      if (booted) {
        send({
          stage: 'update:boot',
          build: running,
          served,
          container: containerOf(win),
          serviceWorker: !!nav.serviceWorker?.controller,
          ...navigationOf(win),
        })
      }
      if (!served || served === running) return
      // 覚えられない画面は移らない (= 入口の頁が古いまま残っていると、 起動の度に読み込み直して抜けられない)
      if (reloadedToRecently(win) === served || !saveReloadedTo(win, served)) {
        send({ stage: 'update:held', from: running, to: served })
        return
      }
      reloadWhenFree(() => {
        send({ stage: 'update:reload', from: running, to: served, serviceWorker: hasServiceWorker })
      })
    })
  }
  const check = () => {
    checkServedBuild()
    if (hasServiceWorker) checkForUpdate(nav)
  }

  win.addEventListener('cpc:fg', check)
  win.addEventListener('cpc:connected', () => {
    if (Date.now() - servedCheckedAt >= CONNECTED_CHECK_GAP_MS) checkServedBuild()
  })
  win.setInterval(() => { if (doc.visibilityState === 'visible') check() }, UPDATE_CHECK_INTERVAL_MS)
  checkServedBuild({ booted: true })
}

// test 用: 配線を付け直せるようにする
export function _resetForTest() { installed = false }
