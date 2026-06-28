// localStorage 一元化 (= state-trace.md § 5)。 11 key の save / load + debounce + quota retry +
// auto-flush on lifecycle (= pagehide / freeze / visibilitychange-hidden)。
//
// v1 utils/storage.js のロジックを継承しつつ、 v2 では state/ の各 store に subscribe して自動 persist する形に。

import * as messages from './messages.js'
import * as sessions from './sessions.js'
import * as ui from './ui.js'

// lz-string は遅延 import (= SSR / test 環境で missing でも死なないように lazy 解決)
let lzCache = null
async function loadLZ() {
  if (lzCache) return lzCache
  try {
    const mod = await import('lz-string')
    lzCache = mod.default || mod
  } catch { lzCache = null }
  return lzCache
}

// localStorage キー (= v1 constants.js と互換)
export const LS = {
  SESSIONS_META: 'cpc_sessions_meta',
  ACTIVE_SESSION: 'cpc_active_session',
  MESSAGES_PREFIX: 'cpc_messages_v2_',  // per-sid (= LZString 圧縮)
  INPUT: 'cpc_input',
  SESSION_ACTIVITY: 'cpc_session_activity',
  JSONL_OFFSET: 'cpc_jsonl_offset',
  VIEW_MODES: 'cpc_view_modes',
  UNREAD_DONE: 'cpc_unread_done',
}

const DEBOUNCE_MS = 500
const QUOTA_RETRY_MAX = 10
const QUOTA_RETRY_TRIM_RATIO = 0.1

const pending = new Map()  // key -> { timer, value }

function lsGetRaw(key) {
  try { return localStorage.getItem(key) } catch { return null }
}

function lsSetRaw(key, value) {
  try { localStorage.setItem(key, value); return true } catch (e) {
    if (e?.name === 'QuotaExceededError') return false
    console.warn('[persistence] set failed', key, e); return false
  }
}

function lsRemove(key) {
  try { localStorage.removeItem(key) } catch { /* ignore */ }
}

export function loadJson(key, fallback = null) {
  const raw = lsGetRaw(key)
  if (raw === null) return fallback
  try { return JSON.parse(raw) } catch { return fallback }
}

export function saveJson(key, value) {
  const serialized = JSON.stringify(value)
  if (lsSetRaw(key, serialized)) return true
  // quota retry: 最古 key を削るのは呼び出し側 (= messages の per-sid GC)
  return false
}

export function saveJsonDebounced(key, value) {
  const existing = pending.get(key)
  if (existing) clearTimeout(existing.timer)
  const timer = setTimeout(() => {
    pending.delete(key)
    saveJson(key, value)
  }, DEBOUNCE_MS)
  pending.set(key, { timer, value })
}

export function flushPending() {
  for (const [key, { timer, value }] of pending.entries()) {
    clearTimeout(timer)
    saveJson(key, value)
  }
  pending.clear()
}

// messages のみ LZString 圧縮 + per-sid 永続化
export async function saveMessagesFor(sid, messagesArr) {
  const lz = await loadLZ()
  const key = LS.MESSAGES_PREFIX + sid
  const json = JSON.stringify(messagesArr)
  const payload = lz ? lz.compressToUTF16(json) : json
  // quota retry: 失敗時は古い sid の messages を削って 1 回だけ再試行
  for (let attempt = 0; attempt < QUOTA_RETRY_MAX; attempt++) {
    if (lsSetRaw(key, payload)) return true
    if (!trimOldestMessages(sid)) return false
  }
  return false
}

export async function loadMessagesFor(sid) {
  const lz = await loadLZ()
  const raw = lsGetRaw(LS.MESSAGES_PREFIX + sid)
  if (!raw) return []
  try {
    const json = lz ? (lz.decompressFromUTF16(raw) || raw) : raw
    const parsed = JSON.parse(json)
    return Array.isArray(parsed) ? parsed : []
  } catch { return [] }
}

function trimOldestMessages(excludeSid) {
  // localStorage を走査して MESSAGES_PREFIX の中で最古を削る (= UTC sort は無いので簡易に最初の 1 件)
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k && k.startsWith(LS.MESSAGES_PREFIX) && k !== LS.MESSAGES_PREFIX + excludeSid) {
        lsRemove(k); return true
      }
    }
  } catch { /* ignore */ }
  return false
}

// auto-flush: store に subscribe して localStorage に反映する
let installed = false
let unsubs = []

export function installAutoPersist() {
  if (installed) return
  installed = true

  // sessions store
  unsubs.push(sessions.subscribe(s => {
    saveJsonDebounced(LS.SESSIONS_META, s.sessions)
    saveJsonDebounced(LS.SESSION_ACTIVITY, s.sessionActivity)
    saveJsonDebounced(LS.UNREAD_DONE, s.unreadDone)
    if (s.activeId !== null) saveJsonDebounced(LS.ACTIVE_SESSION, s.activeId)
  }))

  // ui store (= viewModes だけ persist、 overlay / scroll / keyboard は非永続)
  unsubs.push(ui.subscribe(u => {
    saveJsonDebounced(LS.VIEW_MODES, u.viewModes)
  }))

  // messages store (= per-sid 圧縮 persist、 全 sid 1 回 walk)
  unsubs.push(messages.subscribe(m => {
    for (const [sid, arr] of Object.entries(m)) {
      saveMessagesFor(sid, arr)
    }
  }))

  // lifecycle flush (= ADR-013 BFCache 経路で確実に書き出す)
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pagehide', flushPending)
    window.addEventListener('freeze', flushPending)
  }
}

export function uninstallAutoPersist() {
  if (!installed) return
  installed = false
  for (const u of unsubs) u()
  unsubs = []
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', onVisibility)
    window.removeEventListener('pagehide', flushPending)
    window.removeEventListener('freeze', flushPending)
  }
}

function onVisibility() {
  if (document.visibilityState === 'hidden') flushPending()
}

/** boot 時の初期 hydrate: localStorage から全 store に差し戻す。 */
export async function hydrateAllFromStorage() {
  sessions.hydrate({
    sessions: loadJson(LS.SESSIONS_META, []) || [],
    activeId: loadJson(LS.ACTIVE_SESSION, null),
    sessionActivity: loadJson(LS.SESSION_ACTIVITY, {}) || {},
    unreadDone: loadJson(LS.UNREAD_DONE, {}) || {},
  })
  ui.hydrate({ viewModes: loadJson(LS.VIEW_MODES, {}) || {} })
  // messages は per-sid load を sessions 反映後に並列実行
  const sids = (loadJson(LS.SESSIONS_META, []) || []).map(s => s.sid).filter(Boolean)
  const loaded = await Promise.all(sids.map(async sid => [sid, await loadMessagesFor(sid)]))
  const snapshot = Object.fromEntries(loaded.filter(([, arr]) => arr.length > 0))
  messages.hydrate(snapshot)
}
