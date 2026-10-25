// 開いたままの画面を、 新しく載った build へ移す。
//
// 新しい build が載ると sw.js の中身が変わる (= アプリシェルの cache 名が build ごとに決まる)。
// ブラウザが sw.js の更新を自分で確かめるのは頁の遷移の時なので、 開いたまま裏へ回っていた
// PWA は、 前面へ戻っても確かめに行かない (= 載せ替えた後も古い画面のまま動き続ける。 古い画面は
// 消えた chunk を読みに行って、 後から読み込む部品から先に効かなくなる)。
//
// ここで確かめる機会を足す:
//   - 前面へ戻った時 / ブラウザが保存していた頁を戻した時 (= transport/lifecycle.ts の cpc:fg)
//   - 開いている間は一定の間隔
// 確かめ方は入れ物で 2 つに分かれる:
//   - service worker が在る (= ブラウザ・ホーム画面の PWA): service worker に新しい版を探させ、
//     新しい service worker が有効になったら移る
//   - service worker が無い (= iPhone の app の WKWebView。 App-Bound Domains を宣言しない app には
//     service worker の口が無い): 入口の頁を取り直し、 そこに載っている build が今動かしている
//     build と違えば移る。 app は声の会話を裏で続けるために殺されずに生き続けるので、 これが無いと
//     古い JS が何日も走る
// 移る時は 1 回だけ読み込み直して新しい build の画面へ移る。
// 会話は保存済みで、 打ちかけの入力は頁を離れる時に保存される (= features/chat/useChatStorage.js)
// ので、 読み込み直しでは消えない。 消えるのは、 選んだだけでまだ送っていない添付 (= 選び直しになる)。
// それが在る間は移るのを見送り、 無くなった時 (= 送った / 外した) に移る。 見送っている間も画面は
// 動き続ける (= 1 つ前の build の部品は配られたまま。 build/publishDist.js)。
import { httpClient } from '../transport/http.ts'

// 開いている間に確かめる間隔。 vite-plugin-pwa の手引き (= Periodic Service Worker Updates) の
// 例と同じ 1 時間。
export const UPDATE_CHECK_INTERVAL_MS = 60 * 60 * 1000

// 入口の頁を取り直して移った build を、 頁を跨いで覚えておく鍵。 読み込み直した後もまだ違う
// build が配られている (= 入口の頁がどこかで古いまま残っている) 時に、 読み込み直しを繰り返さない。
const RELOADED_TO_KEY = 'cpc_update_reloaded_to'

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

// backend が今配っている build (= 入口の頁を取り直して読む。 入口の頁は no-cache で配られるので、
// 取るたびに backend へ鮮度を確かめに行く。 backend/_internal/static_files.py)。 取れない時は null。
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

function readReloadedTo(win) {
  try { return win.sessionStorage.getItem(RELOADED_TO_KEY) } catch { return null }
}

function saveReloadedTo(win, build) {
  try { win.sessionStorage.setItem(RELOADED_TO_KEY, build) } catch { /* private mode 等 */ }
}

let installed = false

// unsent = 読み込み直すと消える、 ユーザの手元の物 (= 未送信の添付) の見張り:
//   { hasAny: () => boolean, subscribe: (listener) => unsubscribe }
// 渡さなければ、 見送らずにすぐ移る。
// http = 入口の頁を取り直す口。 send = 入口の頁を取り直して移る時に、 backend の記録
// (= `sw-log` の `update:reload`) へ 1 行送る口。
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

  let check
  if (nav.serviceWorker) {
    // 新しい service worker が有効になった = 新しい build が載った。
    // 初めて登録された時 (= 管理する service worker が無かった頁に付いた時) は更新ではないので数えない。
    let controlled = !!nav.serviceWorker.controller
    nav.serviceWorker.addEventListener('controllerchange', () => {
      if (!controlled) { controlled = true; return }
      reloadWhenFree()
    })
    check = () => { checkForUpdate(nav) }
  } else {
    const running = runningBuildId(doc)
    // 入口の script を持たない頁 (= 開発の server) は、 比べる build が無い
    if (!running) return
    check = () => {
      fetchServedBuildId(http).then(served => {
        if (!served || served === running || readReloadedTo(win) === served) return
        reloadWhenFree(() => {
          saveReloadedTo(win, served)
          send({ stage: 'update:reload', from: running, to: served })
        })
      })
    }
  }

  win.addEventListener('cpc:fg', check)
  win.setInterval(() => { if (doc.visibilityState === 'visible') check() }, UPDATE_CHECK_INTERVAL_MS)
}

// test 用: 配線を付け直せるようにする
export function _resetForTest() { installed = false }
