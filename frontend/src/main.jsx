import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import Terminal from './features/terminal/Terminal.jsx'
import ErrorBoundary from './layout/ErrorBoundary.jsx'
import { hardRefreshAppShell } from './utils/appRefresh.js'

// deploy 後の旧 client 自己修復: lazy chunk の dynamic import 失敗 (= deploy で旧 hash の
// chunk がサーバから消えた) を Vite の vite:preloadError で受け、 「アプリを更新」 と同じ
// 刷新経路を自動発火する。 ユーザには全画面エラーの代わりに 1 回の自動 reload に見える。
// 60s 内の再発は素通し (= 刷新で直らない別問題を無限 reload loop にしない、 その場合は
// ErrorBoundary に落ちて可視化される)。
window.addEventListener('vite:preloadError', (event) => {
  const KEY = 'cpc_auto_refresh_at'
  let last = 0
  try { last = Number(sessionStorage.getItem(KEY) || 0) } catch { /* private mode 等 */ }
  if (Date.now() - last < 60_000) return
  try { sessionStorage.setItem(KEY, String(Date.now())) } catch { /* ignore */ }
  event.preventDefault()
  hardRefreshAppShell()
})

// Service Worker 登録 (Web Push 受信用)。
// iOS PWA は 16.4+ かつホーム画面追加済みでのみ Push を受け取れる。
// 未対応環境では何もしない。
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    // updateViaCache: 'none' で sw.js 自体を毎回 fresh fetch する。
    navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' })
      .catch(() => { /* noop */ })
  })
  // SW 更新時の controller swap で 1 回だけ自動リロード。 これが無いと新版 sw.js が
  // activate されても App.jsx は古い JS のまま走り続け、 SW と App の version 不整合で
  // SW→App の経路 (= 通知タップの open-session 受信) が無音で死ぬ (= 2026-06-09 根本原因)。
  // 初回登録時 (= controller null → 有) の発火は無視するため、 register 前に既に
  // controller が居たケースだけ扱う (= 本物の「更新」)。
  if (navigator.serviceWorker.controller) {
    let reloading = false
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (reloading) return
      reloading = true
      window.location.reload()
    })
  }
}

// ルーティング:
//   `?terminal=<id>`      → xterm.js single-shot (= debug / 直リンク用)
//   それ以外              → App (= chat UI、 受信 JSONL / 送信 tmux send-keys。
//                            生 xterm はタブ単位に ⋯メニューの「ターミナルで表示」 で切替)
const params = new URLSearchParams(window.location.search)
const terminalSessionId = (() => {
  const sid = params.get('terminal')
  return sid && sid.trim() ? sid.trim() : null
})()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary>
      {terminalSessionId ? (
        <div style={{ position: 'fixed', inset: 0, background: '#0e0f12' }}>
          <Terminal sessionId={terminalSessionId} />
        </div>
      ) : (
        <App />
      )}
    </ErrorBoundary>
  </StrictMode>,
)
