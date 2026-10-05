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
// 新しい service worker が有効になったら、 1 回だけ読み込み直して新しい build の画面へ移る。
// 読み込み直しで消える物は無い: 会話は保存済み、 打ちかけの入力は頁を離れる時に保存される
// (= features/chat/useChatStorage.js)。

// 開いている間に確かめる間隔。 vite-plugin-pwa の手引き (= Periodic Service Worker Updates) の
// 例と同じ 1 時間。
export const UPDATE_CHECK_INTERVAL_MS = 60 * 60 * 1000

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

let installed = false

export function installUpdateChecks({ win = window, doc = document, nav = navigator } = {}) {
  if (installed || !nav.serviceWorker) return
  installed = true

  // 新しい service worker が有効になった = 新しい build が載った。 1 回だけ読み込み直す。
  // これが無いと、 新しい sw.js が有効になっても画面は古い JS のまま走り続ける。
  // 初めて登録された時 (= 管理する service worker が無かった頁に付いた時) は更新ではないので数えない。
  let controlled = !!nav.serviceWorker.controller
  let reloading = false
  nav.serviceWorker.addEventListener('controllerchange', () => {
    if (!controlled) { controlled = true; return }
    if (reloading) return
    reloading = true
    win.location.reload()
  })

  const check = () => { checkForUpdate(nav) }
  win.addEventListener('cpc:fg', check)
  win.setInterval(() => { if (doc.visibilityState === 'visible') check() }, UPDATE_CHECK_INTERVAL_MS)
}

// test 用: 配線を付け直せるようにする
export function _resetForTest() { installed = false }
