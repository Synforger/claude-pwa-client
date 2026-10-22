// アプリシェルの強制刷新 (= SW cache 全削除 → 新 SW activate 待ち → cache-bust reload)。
//
// 呼び出し経路は 2 つ、 どちらも同じ刷新に集約する (= 真値 1 箇所):
//   1. SessionDrawer 「↺ アプリを更新」 (= ユーザ明示)
//   2. main.jsx の vite:preloadError handler (= deploy 後の旧 client が消えた chunk を
//      踏んだ瞬間の自動復旧。 sw.js の navigation は network-first になった (= 2026-07-09)
//      ので新規起動は最新 index を取るが、 **既に起動中の tab の最中に deploy された**
//      場合はメモリ上の旧 index が旧 hash chunk を dynamic import して 404 で死ぬ経路が
//      残る。 その瞬間の保険として本刷新を呼ぶ)
// 刷新の前準備 (= cache の削除と、 新しい service worker が有効になるのを待つ) に掛ける上限。
// 前準備がどこかで返らなくても (= 圏外、 service worker の取得が固まる等)、 ここで打ち切って
// 読み込み直しへ進む (= ボタンを押したのに何も起きない、 を作らない)。
export const REFRESH_PREPARE_TIMEOUT_MS = 5000

async function prepareRefresh() {
  // 1. Cache Storage を全削除 (= sw.js の shell キャッシュを一掃)。
  if (typeof caches !== 'undefined') {
    const keys = await caches.keys()
    await Promise.all(keys.map(k => caches.delete(k).catch(() => {})))
  }
  // 2. 新 sw.js を取得し、 install → activate 完了まで待つ (= 待たずに reload すると
  //    古い SW のまま再読み込みして「効かない」 race)。 unregister はしない
  //    (= PushSubscription 維持、 update() で差し替え)。
  if ('serviceWorker' in navigator) {
    const regs = await navigator.serviceWorker.getRegistrations()
    await Promise.all(regs.map(async (r) => {
      try {
        await r.update()
        const incoming = r.installing || r.waiting
        if (incoming && incoming.state !== 'activated') {
          await new Promise((resolve) => {
            incoming.addEventListener('statechange', () => {
              if (incoming.state === 'activated') resolve()
            })
          })
        }
      } catch { /* ignore */ }
    }))
  }
}

export async function hardRefreshAppShell() {
  try {
    await Promise.race([
      prepareRefresh(),
      new Promise(resolve => setTimeout(resolve, REFRESH_PREPARE_TIMEOUT_MS)),
    ])
  } catch { /* ignore */ }
  // 3. cache-bust クエリ付きハードリロード (= navigation を必ず新規リクエスト化)。
  const url = new URL(window.location.href)
  url.searchParams.set('_r', String(Date.now()))
  window.location.replace(url.toString())
}
