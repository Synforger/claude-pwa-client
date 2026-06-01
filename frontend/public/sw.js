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
// メッセージで sid を投げてくる。 push の session-aware 抑制で使う (= LINE 流: 「まさに
// そのトーク見てる時」 だけ抑制、 他は通知する)。 SW 再起動で消える + 死んだ client は
// push 受信時の matchAll で掃除する = stale 概念が原理的に発生しない。
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
    // sid (session id) と url 両方持たせる: native deep link と PWA fallback URL
    data: { id: data.id || null, sid: data.sid || null, url: data.url || '/' },
  }
  // ホーム画面アプリアイコンの未読バッジを更新 (Badging API、 iOS 16.4+ PWA 対応)
  // payload に unread_count が載ってるので fetch 不要 = 完全終了状態でも省電力で更新
  diagLog('push:parsed', { title: data.title, sid: data.sid || null, unreadCount: data.unread_count })
  if (typeof data.unread_count === 'number' && self.navigator && self.navigator.setAppBadge) {
    try { self.navigator.setAppBadge(data.unread_count) } catch { /* ignore */ }
  }
  event.waitUntil((async () => {
    // 抑制方針 (LINE 流): 「focused (= キーボード焦点を持って実際に操作中) かつ
    // active な session が payload の sid と一致」 の時だけ抑制。 visibility は判定に
    // 使わない (= iOS PWA バックグラウンドで matchAll の visibilityState が更新されない
    // バグを回避)。 active 未登録は **抑制しない (fail-open)** = SW 起動直後でも通知が
    // 黙って消えることがない。
    let suppress = false
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
          suppress = true
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
    diagLog('push:suppress-decision', { suppress, clientCount, focusedCount })
    if (suppress) return
    try {
      await self.registration.showNotification(data.title || 'Notification', options)
      diagLog('push:shown', { title: data.title })
    } catch (e) {
      diagLog('push:show-error', { err: String(e) })
    }
  })())
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const data = event.notification.data || {}
  const notifId = data.id  // backend が払い出した通知 id (既読化用)
  // 通知タップは常に chat に着地 (= 旧 native bridge は撤去、 2026-05-16)。
  // 将来 sid からセッションを active にする deep link を再導入する時は data.sid を読む。
  const targetUrl = '/'
  event.waitUntil((async () => {
    // 既読化 (失敗時は無視)
    if (notifId) {
      try {
        await fetch(`/notifications/${encodeURIComponent(notifId)}/read`, { method: 'POST' })
      } catch { /* ignore */ }
    }
    // 既存タブがあれば focus、 無ければ新規開く。
    const allClients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
    for (const client of allClients) {
      if ('focus' in client) {
        try {
          await client.focus()
          if ('navigate' in client) {
            try { await client.navigate(targetUrl) } catch { /* ignore */ }
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
