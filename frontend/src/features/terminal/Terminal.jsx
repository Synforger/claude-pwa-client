/**
 * xterm.js terminal bound to backend `/ws/pty/{sessionId}` WebSocket.
 *
 * The xterm lifecycle (open, WebGL, font load, momentum scroll, native
 * keyboard suppression) is delegated to the useTerminal hook so this file
 * only owns the WebSocket wire + the on-screen input bar.
 *
 * Wire protocol (= matches backend/terminal/routes.py):
 *   server → client:
 *     - binary frames: raw PTY stdout bytes → fed straight into xterm.write()
 *       (= the first one is the pane's current screen, see screenFeed.js)
 *     - text frames (JSON): { type: "exit" | "error" | "snapshot", ... } control messages
 *   client → server:
 *     - binary frames: stdin bytes (= keystrokes / paste)
 *     - text frames (JSON): { type: "resize", rows, cols }
 */
import { useEffect, useRef, useState, useCallback, memo } from 'react'
import { useTerminal } from './useTerminal.js'
import { createScreenFeed } from './screenFeed.js'
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
    // A hidden terminal holds no socket (cleanup closes the previous one) and connects again when it
    // is shown. Keeping the socket and only skipping the drawing made the phone receive and parse
    // every byte of a pane that streams output while another screen was in front, which heated it.
    // Coming back costs one round trip, and the snapshot paints the screen again.
    if (!visible) return undefined

    let cancelled = false
    let backoffMs = 500
    const MAX_BACKOFF = 10_000
    let reconnectTimer = null

    const connect = () => {
      if (cancelled) return
      // PTY WS はこの直書きが正 (= 旧 transport/ws-pty.ts 抽象化案は一度も配線されないまま
      // 2026-07-27 に退役、 xterm.js lifecycle と密結合なためここで完結させる)。
      // eslint-disable-next-line no-restricted-syntax
      const ws = new WebSocket(`${wsBase}/ws/pty/${encodeURIComponent(sessionId)}`)
      ws.binaryType = 'arraybuffer'
      wsRef.current = ws

      // Every connection starts from the backend's snapshot of the pane's current screen,
      // so the terminal asks for no repaint of its own (the size it sends first tells the
      // backend what size to capture at).
      const feed = createScreenFeed({
        terminal,
        sendKeys: (keys) => {
          if (ws.readyState === WebSocket.OPEN) ws.send(new TextEncoder().encode(keys))
        },
        onExit,
      })
      ws.addEventListener('open', () => {
        backoffMs = 500
        const dims = getDimensions()
        if (dims) {
          ws.send(JSON.stringify({ type: 'resize', rows: dims.rows, cols: dims.cols }))
        }
      })

      // A hidden terminal has no socket (it is closed on hide), so a message here is for a visible one.
      ws.addEventListener('message', (ev) => feed.handleMessage(ev.data))

      const scheduleReconnect = (reason) => {
        if (cancelled) return
        terminal.write(
          `\r\n\x1b[2m[disconnected: ${reason}, retry in ${String(Math.round(backoffMs / 100) / 10)}s]\x1b[0m\r\n`,
        )
        reconnectTimer = setTimeout(() => {
          backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF)
          connect()
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

    connect()

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
