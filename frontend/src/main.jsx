import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import Terminal from './components/Terminal.jsx'
import ErrorBoundary from './ErrorBoundary.jsx'

// Service Worker 登録 (Web Push 受信用)。
// iOS PWA は 16.4+ かつホーム画面追加済みでのみ Push を受け取れる。
// 未対応環境では何もしない。
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    // updateViaCache: 'none' で sw.js 自体を毎回 fresh fetch する (= デフォルト 'imports'
    // だと HTTP cache 経由になり、 iOS Safari で SW 更新が大幅に遅延する事例がある)。
    // register 直後と visibility 復帰時に明示的 update() を呼んで新版反映を促す。
    navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' })
      .then(reg => {
        reg.update().catch(() => {})
        document.addEventListener('visibilitychange', () => {
          if (!document.hidden) reg.update().catch(() => {})
        })
      })
      .catch(() => { /* noop */ })
  })
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
