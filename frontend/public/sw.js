// Service Worker for Web Push (iOS PWA / Android Chrome compatible)
//
// 仕様 (W3C Push API + Notifications API): push イベント受信時に
// showNotification を呼べば OS 通知として表示される。
// アプリが完全終了していても OS が SW を起こしてくれるので届く。

self.addEventListener('install', (event) => {
  event.waitUntil(self.skipWaiting())
})

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim())
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
    diagLog('push:decision', { isSelfViewing, clientCount, focusedCount })
    try {
      await self.registration.showNotification(data.title || 'Notification', {
        ...options,
        silent: isSelfViewing,
      })
      // 自分が見てる session 宛は、 表示後すぐに close することでバナー/通知センター
      // からも消す (= 仕様上 showNotification は呼ぶ義務があるので、 呼んだ直後に取り
      // 下げる)。 iOS でバナーが一瞬チラつく可能性はあるが、 通知センターには残らない。
      if (isSelfViewing) {
        try {
          const list = await self.registration.getNotifications({ tag: options.tag })
          for (const n of list) { try { n.close() } catch { /* ignore */ } }
        } catch { /* ignore */ }
      }
      diagLog('push:shown', { title: data.title, silent: isSelfViewing, autoClose: isSelfViewing })
    } catch (e) {
      diagLog('push:show-error', { err: String(e) })
    }
  })())
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const data = event.notification.data || {}
  const sid = data.sid || null
  // backend が payload に "/?ses={sid}" を入れてくる (= 新規ウィンドウ open 用 fallback URL)。
  const targetUrl = data.url || (sid ? `/?ses=${encodeURIComponent(sid)}` : '/')
  event.waitUntil((async () => {
    const allClients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    // 既存タブがあれば focus + postMessage で sid を伝える (= App が activeSid を切替)。
    // navigate() はオリジン内 URL 変更で SPA を full reload しないので、 postMessage の方が
    // 既存 state を保ったまま session 切替できて軽い。
    for (const client of allClients) {
      if ('focus' in client) {
        try {
          await client.focus()
          if (sid) {
            try { client.postMessage({ type: 'open-session', sid }) } catch { /* ignore */ }
          }
          return
        } catch { /* ignore */ }
      }
    }
    if (self.clients.openWindow) {
      try { await self.clients.openWindow(targetUrl) } catch { /* ignore */ }
    }
  })())
})
