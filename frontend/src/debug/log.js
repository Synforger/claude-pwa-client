// ADR-012 frontend 構造化 log writer。 console を wrap して backend /log/* に POST、
// frontend <-> backend log を corr_id で結合する。
//
// 経路:
//   captureConsole() で console.log / warn / error を hook、 既存挙動は維持しつつ structured
//   payload を ring buffer に積む。 flush() で /log/sw に bulk POST、 失敗 (= offline / 5xx)
//   は ring に残して次回 flush でリトライ (= 後段が結合できる前提を壊さない)。
//
//   transport/correlation.ts の listRecent() を使うと、 直近 fetch ↔ corr_id の対応が取れる。
//   この log writer 自体は fetch を transport 経由で呼ぶ (= no-restricted-syntax 違反回避)。

import { httpClient } from '../transport/http.ts'

const MAX_BUFFER = 200
const FLUSH_INTERVAL_MS = 2_000

let buffer = []
let installed = false
let flushTimer = null
const originals = { log: null, info: null, warn: null, error: null, debug: null }

function nowIso() {
  return new Date().toISOString()
}

function safeStringify(arg) {
  if (typeof arg === 'string') return arg
  try { return JSON.stringify(arg) } catch { return String(arg) }
}

function pushEntry(level, args) {
  if (buffer.length >= MAX_BUFFER) buffer.shift()
  buffer.push({
    '@timestamp': nowIso(),
    level,
    event: 'console',
    message: args.map(safeStringify).join(' '),
    args_count: args.length,
  })
}

export function captureConsole() {
  if (installed) return
  installed = true
  for (const level of ['log', 'info', 'warn', 'error', 'debug']) {
    if (typeof console[level] !== 'function') continue
    originals[level] = console[level].bind(console)
    console[level] = (...args) => {
      try { pushEntry(level, args) } catch (e) { originals[level]?.('[log.js] capture failed', e) }
      originals[level]?.(...args)
    }
  }
  if (flushTimer === null && typeof setInterval === 'function') {
    flushTimer = setInterval(() => { flush().catch(() => { /* retry next tick */ }) }, FLUSH_INTERVAL_MS)
  }
}

export function uninstallConsole() {
  if (!installed) return
  installed = false
  for (const level of Object.keys(originals)) {
    if (originals[level]) console[level] = originals[level]
    originals[level] = null
  }
  if (flushTimer !== null) {
    clearInterval(flushTimer)
    flushTimer = null
  }
}

export async function flush() {
  if (buffer.length === 0) return { sent: 0 }
  const batch = buffer.slice()
  buffer = []
  try {
    await httpClient.apiFetch('/log/sw', {
      method: 'POST',
      jsonBody: { event: 'frontend_log_batch', entries: batch },
      timeout: 5_000,
    })
    return { sent: batch.length }
  } catch (e) {
    // 失敗時は ring buffer 先頭に戻す (= overflow したら新しい方を保持)
    const overflow = Math.max(0, buffer.length + batch.length - MAX_BUFFER)
    buffer = [...batch.slice(overflow), ...buffer]
    throw e
  }
}

export function getBufferSnapshot() {
  return buffer.slice()
}

export function clearBuffer() {
  buffer = []
}
