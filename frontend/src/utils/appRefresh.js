// アプリシェルの強制刷新 (= SW cache 全削除 → 新 SW activate 待ち → cache-bust reload)。
//
// 呼び出し経路は 2 つ、 どちらも同じ刷新に集約する (= 真値 1 箇所):
//   1. SessionDrawer 「↺ アプリを更新」 (= ユーザ明示)
//   2. main.jsx の vite:preloadError handler (= deploy 後の旧 client が消えた chunk を
//      踏んだ瞬間の自動復旧。 sw.js は navigation cache-first + /assets/ はオンデマンド
//      cache のみなので、 deploy で旧 hash chunk がサーバから消えると旧 index の
//      dynamic import が 404 で死ぬ。 2026-07-05 の全画面エラー多発の構造原因)
export async function hardRefreshAppShell() {
  try {
    // 1. Cache Storage を全削除 (= sw.js の shell キャッシュを一掃)。
    if (typeof caches !== 'undefined') {
      const keys = await caches.keys()
      await Promise.all(keys.map(k => caches.delete(k).catch(() => {})))
    }
    // 2. 新 sw.js を取得し、 install → activate 完了まで待つ (= 待たずに reload すると
    //    古い SW のまま再読み込みして「効かない」 race)。 unregister はしない
    //    (= PushSubscription 維持、 update() で差し替え)。 最大 5s で打ち切り。
    if ('serviceWorker' in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations()
      await Promise.all(regs.map(async (r) => {
        try {
          await r.update()
          const incoming = r.installing || r.waiting
          if (incoming && incoming.state !== 'activated') {
            await new Promise((resolve) => {
              const done = setTimeout(resolve, 5000)
              incoming.addEventListener('statechange', () => {
                if (incoming.state === 'activated') { clearTimeout(done); resolve() }
              })
            })
          }
        } catch { /* ignore */ }
      }))
    }
  } catch { /* ignore */ }
  // 3. cache-bust クエリ付きハードリロード (= navigation を必ず新規リクエスト化)。
  const url = new URL(window.location.href)
  url.searchParams.set('_r', String(Date.now()))
  window.location.replace(url.toString())
}
