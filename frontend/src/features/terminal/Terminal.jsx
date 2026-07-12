/**
 * xterm.js terminal bound to backend `/ws/pty/{sessionId}` WebSocket.
 *
 * The xterm lifecycle (open, WebGL, font load, momentum scroll, native
 * keyboard suppression) is delegated to the useTerminal hook so this file
 * only owns the WebSocket wire + the on-screen input bar.
 *
 * Wire protocol (= matches backend/pty_routes.py):
 *   server → client:
 *     - binary frames: raw PTY stdout bytes → fed straight into xterm.write()
 *     - text frames (JSON): { type: "exit" | "error", ... } control messages
 *   client → server:
 *     - binary frames: stdin bytes (= keystrokes / paste)
 *     - text frames (JSON): { type: "resize", rows, cols }
 */
import { useEffect, useRef, useState, useCallback, memo } from 'react'
import { useTerminal } from './useTerminal.js'
import OnScreenKeyboard from '../ios-native/OnScreenKeyboard.jsx'
import { useT } from '../../i18n/t.js'

const DEFAULT_WS_BASE =
  (typeof window !== 'undefined' && window.location.protocol === 'https:'
    ? 'wss://'
    : 'ws://') +
  (typeof window !== 'undefined' ? window.location.host : 'localhost:8765')


function TerminalImpl({ sessionId, wsBase = DEFAULT_WS_BASE, onExit, visible = true }) {
  const t = useT()
  const containerRef = useRef(null)
  const { terminal, getDimensions, scrollToBottom } = useTerminal(containerRef)

  // ADR-022 e2e seam: expose a minimal buffer snapshot helper on window so
  // playwright scenarios can assert what xterm actually rendered (its canvas
  // / WebGL output is otherwise opaque to the DOM). Kept in prod builds too
  // - it is a pure read of an in-memory buffer with zero side effects, no
  // wider surface than xterm.js itself already exposes if you have a `term`
  // ref. Removing it would force scenarios to depend on canvas rasterisation.
  useEffect(() => {
    if (!terminal) return
    window.__cpcTerm = {
      snapshot: (rows = terminal.rows) => {
        const buf = terminal.buffer?.active
        if (!buf) return ''
        const lines = []
        const start = Math.max(0, buf.length - rows)
        for (let i = start; i < buf.length; i++) {
          const line = buf.getLine(i)
          if (line) lines.push(line.translateToString(true))
        }
        return lines.join('\n')
      },
    }
    return () => { delete window.__cpcTerm }
  }, [terminal])

  const wsRef = useRef(null)
  const inputRef = useRef(null)
  const [inputValue, setInputValue] = useState('')
  // フルオンスクリーンキーボード (= 矢印 / Ctrl / Tab / 記号等、 物理キーボードの無い
  // モバイルで TUI を直操作するため) の表示トグル。 縦を食うので既定 OFF。
  const [showKbd, setShowKbd] = useState(false)

  // 発熱対策 (= 2026-07-13、 旧 F-11 hidden buffer を置換): hidden Terminal は WS ごと
  // 切断する。 旧方式 (= 描画だけ skip して受信は継続) は、 agent が端末出力を吹き出す
  // 使い方だと chat 画面を見ている間も全 PTY バイトを無線受信 + 処理し続け、 携帯の
  // 発熱の主犯級だった。 visible 復帰時は再接続 + terminal.reset() + Ctrl-L で TUI に
  // 最新画面を描き直させる (= backend 側も backlog drain + Ctrl-L 再描画が公式経路、
  // scrollback 自動復元は描画破綻のため 2026-05-21 に廃止済み)。 切替コストは再接続
  // 1 往復 (= LAN で体感 0.1-0.3s)、 「見てない端末の生映像」 と引き換えに受信ゼロ。
  const hasConnectedRef = useRef(false)

  // Common byte/string sink to the live WS — used by control-key buttons and
  // the input bar. No-ops while the socket is not open.
  const sendRaw = useCallback((data) => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    if (typeof data === 'string') {
      ws.send(new TextEncoder().encode(data))
    } else {
      ws.send(data)
    }
  }, [])

  const flushInput = useCallback(
    (withReturn) => {
      if (inputValue) sendRaw(inputValue)
      if (withReturn) sendRaw('\r')
      setInputValue('')
      inputRef.current?.focus()
    },
    [inputValue, sendRaw],
  )

  // WebSocket lifecycle: connect once the terminal is open, reconnect with
  // exponential backoff on close/error, and pump stdout into xterm.
  useEffect(() => {
    if (!terminal) return undefined
    // hidden = 接続しない (= cleanup が直前接続を閉じる)。 visible 復帰で再接続。
    if (!visible) return undefined

    let cancelled = false
    let backoffMs = 500
    const MAX_BACKOFF = 10_000
    let reconnectTimer = null

    const connect = (isReconnect = false) => {
      if (cancelled) return
      // TODO Phase F-terminal-ws: transport/ws-pty.ts ptyTransport.connect(sid, handler) 経由に
      // 書換。 xterm.js lifecycle (= reset / redraw / Ctrl-L re-attach / exponential backoff) と
      // ws-pty.ts の heartbeat / state machine を整合させる作業が必要、 W2 物理移送 commit から
      // 切り出して別 commit で実装。 ADR-018 features → transport 直接 import は許可済。
      // eslint-disable-next-line no-restricted-syntax
      const ws = new WebSocket(`${wsBase}/ws/pty/${encodeURIComponent(sessionId)}`)
      ws.binaryType = 'arraybuffer'
      wsRef.current = ws

      ws.addEventListener('open', () => {
        backoffMs = 500
        // 再接続時は既存バッファを全消し → Ctrl-L で TUI に現状描画させる。
        // 消さずに Ctrl-L だけ送ると、 redraw された画面が既存内容の下に積み重なる
        // (= disconnect 連発で同じ画面が 2、 3 倍に重複する事故、 2026-06-11 報告)。
        if (isReconnect) terminal.reset()
        const dims = getDimensions()
        if (dims) {
          ws.send(JSON.stringify({ type: 'resize', rows: dims.rows, cols: dims.cols }))
        }
        ws.send(new TextEncoder().encode('\x0c'))
      })

      ws.addEventListener('message', (ev) => {
        if (typeof ev.data === 'string') {
          try {
            const ctrl = JSON.parse(ev.data)
            if (ctrl.type === 'exit') {
              terminal.write(
                `\r\n\x1b[31m[backend reports PTY exited rc=${ctrl.returncode}]\x1b[0m\r\n`,
              )
              onExit?.(ctrl)
            } else if (ctrl.type === 'error') {
              terminal.write(`\r\n\x1b[31m[backend error: ${ctrl.message}]\x1b[0m\r\n`)
            }
          } catch { /* ignore */ }
          return
        }
        // hidden 中は WS 自体が閉じているので、 ここに来る = visible。 即 write。
        terminal.write(new Uint8Array(ev.data))
      })

      const scheduleReconnect = (reason) => {
        if (cancelled) return
        terminal.write(
          `\r\n\x1b[2m[disconnected: ${reason}, retry in ${String(Math.round(backoffMs / 100) / 10)}s]\x1b[0m\r\n`,
        )
        reconnectTimer = setTimeout(() => {
          backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF)
          connect(true)
        }, backoffMs)
      }

      ws.addEventListener('close', (ev) => scheduleReconnect(`close ${String(ev.code)}`))
      ws.addEventListener('error', () => {
        try { ws.close() } catch { /* noop */ }
      })
    }

    // Send resize updates whenever xterm reflows (= fit() recomputed cols/rows).
    const onResizeDisposable = terminal.onResize((size) => {
      const ws = wsRef.current
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'resize', rows: size.rows, cols: size.cols }))
      }
    })

    // 2 回目以降の visible 復帰は reconnect 扱い (= reset + Ctrl-L 再描画)。
    connect(hasConnectedRef.current)
    hasConnectedRef.current = true

    return () => {
      cancelled = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      onResizeDisposable.dispose()
      try { wsRef.current?.close() } catch { /* noop */ }
      wsRef.current = null
    }
  }, [terminal, sessionId, wsBase, onExit, getDimensions, visible])

  // Keystrokes from a physical keyboard (if any) → WS direct. The on-screen
  // input bar bypasses this and uses sendRaw directly.
  useEffect(() => {
    if (!terminal) return undefined
    const disposable = terminal.onData((data) => {
      scrollToBottom()
      const ws = wsRef.current
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data))
      }
    })
    return () => disposable.dispose()
  }, [terminal, scrollToBottom])

  // Container padding-free wrapper: WebGL canvas is positioned from the host
  // origin, so any padding shifts the canvas by ~1 cell. Apply outer spacing
  // on the parent if needed instead of here.
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        width: '100%',
        height: '100%',
        background: '#0e0f12',
      }}
      data-testid="terminal-pane"
    >
      <div
        ref={containerRef}
        style={{ flex: 1, minHeight: 0, width: '100%', background: '#0e0f12' }}
        data-testid="terminal-output"
      />
      <div
        style={{
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          gap: 4,
          padding: '6px 6px 8px',
          background: '#15171c',
          borderTop: '1px solid #2a2d35',
        }}
      >
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            ref={inputRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            data-testid="terminal-input"
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                flushInput(true)
              }
            }}
            autoCapitalize="off"
            autoCorrect="off"
            autoComplete="off"
            spellCheck={false}
            placeholder={t('terminal.input_placeholder')}
            style={inputStyle}
          />
          <button
            type="button"
            onClick={() => flushInput(true)}
            style={{ ...keyBtnStyle, background: '#3a5a8c', color: '#fff', minWidth: 56 }}
          >Send</button>
        </div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          <button type="button" onClick={() => sendRaw('\x1b')} style={keyBtnStyle}>Esc</button>
          <button type="button" onClick={() => sendRaw('\r')} style={keyBtnStyle}>Enter</button>
          <button type="button" onClick={() => sendRaw('\x03')} style={keyBtnStyle}>Ctrl-C</button>
          <button type="button" onClick={() => sendRaw('\t')} style={keyBtnStyle}>Tab</button>
          <button
            type="button"
            onClick={() => setShowKbd((v) => !v)}
            style={{ ...keyBtnStyle, marginLeft: 'auto', background: showKbd ? '#3a5a8c' : '#2a2d35', color: '#fff' }}
          >⌨ {showKbd ? t('terminal.keyboard_hide') : t('terminal.keyboard_show')}</button>
        </div>
      </div>
      {showKbd && <OnScreenKeyboard onKey={sendRaw} />}
    </div>
  )
}

// F-01 (= 2026-06-21): React.memo で wrap、 App.jsx が messages flush 等で再 render しても
// Terminal は props (= sessionId / wsBase / onExit / visible) が変わらない限り再 render しない。
// 旧実装は App.jsx 再 render で全 sid Terminal も巻き込まれて reconciliation コストが
// 走っていた (= xterm.js 自体は ref で隠れて re-mount しないが、 React 木の比較は走る)。
// props は全部 primitive / mount 時固定なので shallow compare で十分。
const Terminal = memo(TerminalImpl)
export default Terminal

const inputStyle = {
  flex: 1,
  minWidth: 0,
  background: '#0e0f12',
  color: '#e6e6e6',
  border: '1px solid #2a2d35',
  borderRadius: 4,
  padding: '6px 8px',
  fontFamily: 'Menlo, monospace',
  // 16px keeps iOS Safari from auto-zooming on input focus. viewport meta
  // also sets user-scalable=no but older iOS versions ignore that.
  fontSize: 16,
}

const keyBtnStyle = {
  background: '#2a2d35',
  color: '#e6e6e6',
  border: '1px solid #3a3d45',
  borderRadius: 4,
  padding: '6px 10px',
  fontSize: 13,
  fontFamily: 'Menlo, monospace',
  cursor: 'pointer',
  flexShrink: 0,
  minWidth: 38,
  touchAction: 'manipulation',
}
