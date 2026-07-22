// Service Worker for Web Push (iOS PWA / Android Chrome compatible)
//
// 仕様 (W3C Push API + Notifications API): push イベント受信時に
// showNotification を呼べば OS 通知として表示される。
// アプリが完全終了していても OS が SW を起こしてくれるので届く。

// アプリシェル (HTML / JS / CSS) のキャッシュ世代名。 version を上げると activate で旧世代を
// 全削除する (= 確実な刷新経路)。 sw.js は backend が no-cache で配信するので、 新しい sw.js は
// PWA 起動時に必ず取得される → install → activate で旧キャッシュ一掃 → 最新 bundle に入れ替わる。
// v3 (= 2026-07-09): navigation を network-first へ戻すと同時に bump。 旧 v2 世代には
// cache-first 時代の複数世代 index.html が URL query 違い (`/` / `/?ses=` / `/?_r=`) で
// 分裂堆積しており、 それが「起動経路ごとに新旧がばらつく」 更新地獄の温床だったので一掃する。
// v4: frontend bundle 差し替え時は必ずこの版を上げる (= 上げないと新 SW が立たず、 古い
// キャッシュの index が差し替えで消えた chunk を踏んで白画面になる)。 bump = 新 SW install
// (skipWaiting) → activate で旧 shell cache 全削除 → controllerchange で 1 回自動リロード
// = 全 client がクリーンに最新 bundle へ移行する。
const SHELL_CACHE = 'claude-pwa-shell-v11'

self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting())
})

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    // 旧世代の shell キャッシュを全削除 (= version 切替時の刷新)。
    const keys = await caches.keys()
    await Promise.all(keys.filter((k) => k !== SHELL_CACHE).map((k) => caches.delete(k)))
    await self.clients.claim()
  })())
})

// アプリシェルの fetch 戦略 (= 2026-07-09 再改定、 「更新地獄」 の根治)。
//
// 経緯: 2026-06-22 に navigation を network-first → cache-first にした (= 「起動毎に再読み込み
// されて再マウントしてる感覚」 対策)。 しかしこれは副作用として **新 build が永遠に反映されない**
// 更新地獄を生んだ。 しかも navigation を cache-first にすると、 キャッシュ key が URL 完全一致
// (= query 込み) なので、 起動経路ごとに違う URL (`/` / `/?ses=<sid>` / `/?_r=<ts>`) が別々の
// 世代の index.html を保持して分裂堆積し、 「起動の仕方によって新旧がばらつく (= たまに古い版が
// 出る)」 症状になっていた。
//
// 対策: navigation を **network-first (cache fallback)** に戻す。 index.html は数百 byte で
// 毎起動 fetch しても軽い。 「状態リセット」 の懸念は誤りだった (= 会話 / activeId 等の状態は
// localStorage にあり SW cache とは無関係、 index の取得方法を変えてもリセットされない)。
// cache 保存は **単一キー `/` に正規化**して query 違いの世代分裂を根絶する。
//   - navigation (index.html) : network-first。 成功時は常に最新 index を返し `/` 単一キーに
//     保存。 失敗時 (= オフライン) のみ `/` cache にフォールバック (= 圏外でも起動可能)。
//   - hashed assets (/assets/*) / manifest / アイコン : cache-first (= 内容不変、 hash で世代分離)。
//   - API / SSE / WS / 非 GET : 一切 respondWith せず素通り (= ストリーム系を壊さない)。
self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return
  const url = new URL(req.url)
  if (url.origin !== self.location.origin) return

  // HTML ナビゲーション = network-first (= 常に最新 index、 オフライン時のみ cache fallback)。
  if (req.mode === 'navigate') {
    event.respondWith((async () => {
      try {
        const fresh = await fetch(req)
        if (fresh && fresh.ok) {
          const cache = await caches.open(SHELL_CACHE)
          // 単一キー `/` に正規化して保存 (= `/?ses=` / `/?_r=` 等の起動経路 URL 違いで
          // 世代が分裂堆積するのを防ぐ、 更新地獄の直接原因を断つ)。
          cache.put('/', fresh.clone())
        }
        return fresh
      } catch {
        // オフライン: 単一キー `/` の cache にフォールバック (= 圏外でも起動可能)。
        const cached = await caches.match('/')
        return cached || Response.error()
      }
    })())
    return
  }

  // 静的アセットだけ cache-first。 それ以外 (= API / SSE / WS) は介入しない。
  const isShellAsset =
    url.pathname.startsWith('/assets/') ||
    url.pathname === '/manifest.json' ||
    url.pathname.endsWith('.svg') ||
    url.pathname.endsWith('.png') ||
    url.pathname.endsWith('.ico')
  if (!isShellAsset) return

  event.respondWith((async () => {
    const cached = await caches.match(req)
    if (cached) return cached
    const fresh = await fetch(req)
    if (fresh && fresh.ok) {
      const cache = await caches.open(SHELL_CACHE)
      cache.put(req, fresh.clone())
    }
    return fresh
  })())
})

// 各 client (= タブ) が「今どの session を見ているか」 を保持。 App.jsx が active-session
// メッセージで sid を投げてくる。 push の silent 判定で使う (= 自分が見てる session 宛の
// 通知だけ silent=true で控えめにする)。 SW 再起動で消える + 死んだ client は push 受信時の
// matchAll で掃除する = stale 概念が原理的に発生しない。
const clientActive = {}

self.addEventListener('message', (event) => {
  const d = event.data
  if (d && d.type === 'active-session' && event.source && event.source.id) {
    clientActive[event.source.id] = { sid: d.sid || null }
  }
})

// 診断ログ: SW 内 console は実機 (iOS PWA) から見れないので backend に POST して
// logs/backend.log に集約する。 通知が届かない時の切り分けに使う。
// fetch 失敗は無視 (= keepalive ベストエフォート)。
function diagLog(stage, extra) {
  try {
    fetch('/log/sw', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      keepalive: true,
      body: JSON.stringify({ stage, ...extra }),
    }).catch(() => {})
  } catch { /* ignore */ }
}

self.addEventListener('push', (event) => {
  diagLog('push:received', { hasData: !!event.data })
  let data = { title: 'Notification', body: '' }
  try {
    if (event.data) {
      const json = event.data.json()
      if (typeof json === 'object' && json) {
        data = { ...data, ...json }
      }
    }
  } catch {
    // 文字列ペイロードはそのまま body に
    try { data.body = event.data.text() } catch { /* ignore */ }
  }

  const options = {
    body: data.body || '',
    icon: '/icon-192.svg',
    badge: '/icon-192.svg',
    tag: data.tag || 'proactive',
    renotify: true,
    // sid (session id) と url 両方持たせる: notificationclick で sid → activeSid 切替、
    // url は新規ウィンドウ open 時の deep link fallback。
    data: { sid: data.sid || null, url: data.url || '/' },
  }
  // ホーム画面アプリアイコンの未読バッジを更新 (Badging API、 iOS 16.4+ PWA 対応)
  // payload に unread_count が載ってるので fetch 不要 = 完全終了状態でも省電力で更新
  diagLog('push:parsed', { title: data.title, sid: data.sid || null, unreadCount: data.unread_count })
  if (typeof data.unread_count === 'number' && self.navigator && self.navigator.setAppBadge) {
    try { self.navigator.setAppBadge(data.unread_count) } catch { /* ignore */ }
  }
  event.waitUntil((async () => {
    // 方針 (W3C 標準 + iOS Safari 仕様準拠): push を受けたら **必ず showNotification を
    // 呼ぶ**。 呼ばないと iOS が「silent push」 と判定し、 3 回連続で発生すると
    // PushSubscription を強制破棄する (= 「放置で通知失効」 の根本原因)。
    // 「自分が見てる session 宛」 の通知は silent=true (= 音/振動なし、 バナーは出るが
    // 控えめ) にして主張を弱める。 これが「常に showNotification + silent オプション」
    // という Web Push 業界標準パターン。
    let isSelfViewing = false
    let clientCount = 0
    let focusedCount = 0
    try {
      const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      clientCount = all.length
      const liveIds = new Set()
      for (const c of all) {
        liveIds.add(c.id)
        const active = clientActive[c.id]
        const focused = !!c.focused
        if (focused) focusedCount++
        if (data.sid && focused && active && active.sid === data.sid) {
          isSelfViewing = true
        }
        try { c.postMessage({ type: 'push-received', sid: data.sid || null }) } catch { /* ignore */ }
      }
      // 死んだ client の active state を掃除 (= SW 再起動でも消えるが定期的にも縮める)。
      for (const id of Object.keys(clientActive)) {
        if (!liveIds.has(id)) delete clientActive[id]
      }
    } catch (e) {
      diagLog('push:matchAll-error', { err: String(e) })
    }
    // セッションごとの通知モード (both / banner / off) と「自分が見てる session」 を合成して
    // silent / autoClose を決める。 **どの分岐でも showNotification は必ず呼ぶ** (= silent push
    // 判定を避けて iOS の subscription 破棄を構造的に回避する不変条件)。
    //   - 見てる session、 または off : silent + 直後に close (= バナー/通知センターに残さない)
    //   - banner                      : silent バナー (= 音なし、 通知センターには残る)
    //   - both (既定)                 : 音 + バナー
    const mode = data.notify_mode || 'both'
    let silent, autoClose
    if (isSelfViewing || mode === 'off') {
      silent = true; autoClose = true
    } else if (mode === 'banner') {
      silent = true; autoClose = false
    } else {
      silent = false; autoClose = false
    }
    diagLog('push:decision', { isSelfViewing, mode, silent, autoClose, clientCount, focusedCount })
    try {
      // iOS Safari の SW が更新サイクル等で registration.showNotification を失う持病があり
      // (= 2026-06-03 実測)、 その場合 showNotification を呼べず「silent push」 扱いで 3 回
      // 連続→ subscription 破棄 (= 通知が勝手に無効化される根本原因)。 壊れてる時は「registration
      // 自体が無いのか / メソッドだけ無いのか」 を診断ログに残す (= 次回の切り分け材料)。
      const reg = self.registration
      if (!reg || typeof reg.showNotification !== 'function') {
        diagLog('push:reg-broken', {
          hasReg: !!reg,
          regType: typeof reg,
          showType: reg ? typeof reg.showNotification : 'no-reg',
          scope: reg ? reg.scope : null,
        })
        // F-19 (= 2026-06-21): 失効を検出したら回復を試みる。
        //   1. registration.update() で新しい SW を取得し直す (= 軽量回復経路、 register
        //      失敗なら何もしない)
        //   2. 全 client に 'sw-broken' postMessage を投げて App 側 (= usePushSubscription)
        //      に SW unregister + reload させる (= 確実な回復経路)
        // 1 で治れば 2 の reload も結果的に害なし (= 新 reg を取りに行くだけ)、 1 で治らず
        // 2 だけが効くケースもある。 どちらか効けば次回 push は通る。
        try { if (reg && typeof reg.update === 'function') reg.update() } catch { /* ignore */ }
        try {
          const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
          for (const c of clients) {
            try { c.postMessage({ type: 'sw-broken', reason: 'showNotification-missing' }) } catch { /* ignore */ }
          }
        } catch { /* ignore */ }
        return
      }
      await reg.showNotification(data.title || 'Notification', {
        ...options,
        silent,
      })
      // autoClose: showNotification は呼ぶ義務があるので、 呼んだ直後に取り下げる。
      // iOS でバナーが一瞬チラつく可能性はあるが、 通知センターには残らない。
      if (autoClose) {
        try {
          const list = await self.registration.getNotifications({ tag: options.tag })
          for (const n of list) { try { n.close() } catch { /* ignore */ } }
        } catch { /* ignore */ }
      }
      diagLog('push:shown', { title: data.title, silent, autoClose })
    } catch (e) {
      diagLog('push:show-error', { err: String(e) })
    }
  })())
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const data = event.notification.data || {}
  const sid = data.sid || null
  // 経路は 2 つだけ:
  //   (a) ホット = PWA が起動中: matchAll で controlled client 取得 → 全員に postMessage、
  //       1 つを focus でフォアに引き上げる。 SW と App は controllerchange で version 整合済。
  //   (b) コールド = PWA 完全終了: openWindow('/?ses=<sid>') で新規起動、 App.jsx は起動時に
  //       URL param を読んで activeId を反映する。 cold start の唯一の経路なので汚さではなく仕様。
  const targetUrl = sid ? `/?ses=${encodeURIComponent(sid)}` : '/'
  event.waitUntil((async () => {
    const allClients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    if (allClients.length > 0) {
      if (sid) {
        for (const client of allClients) {
          try { client.postMessage({ type: 'open-session', sid }) } catch { /* ignore */ }
        }
      }
      for (const client of allClients) {
        if ('focus' in client) {
          try { await client.focus(); break } catch { /* ignore */ }
        }
      }
      return
    }
    if (self.clients.openWindow) {
      try { await self.clients.openWindow(targetUrl) } catch { /* ignore */ }
    }
  })())
})
