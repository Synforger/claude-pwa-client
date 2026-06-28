import { useCallback, useEffect, useSyncExternalStore } from 'react'
import {
  LS_ACTIVE_SESSION,
  LS_LEGACY_ACTIVE_AGENT,
  LS_SESSIONS_META,
} from '../../constants.js'
import { apiFetch } from '../../utils/api.js'
import { lsGet, lsSet } from '../../utils/storage.js'
import {
  subscribe,
  getSnapshot,
  setSessions,
  appendSession,
  setActiveId as storeSetActiveId,
  setAgents,
} from '../../state/sessions.js'

// セッション (= UI 上の 1 タブ = 1 議題) のリストと、 現在 active な session_id を管理する。
// backend `/sessions` を真値とし、 起動時に GET でローカルの localStorage と同期する。
// ローカル先読みでオフライン時の表示を維持しつつ、 ネットワーク復帰時に backend を信頼する。
//
// W2 Phase E-2 (= 2026-06-29): 旧 useState 3 本を state/sessions.js singleton store へ集約。
// 複数 component (= AppShell / SessionDrawer 等) から本 hook が呼ばれる前提で、 副作用は
// module-level guard で 1 回限定 + 永続化 useEffect は副作用が冪等 (= 同値書込は無害) なので
// 各 instance で走らせて差し支えない。 mutation API は export 関数として直呼出も可。

let lsHydrated = false
let backendInitRequested = false

function hydrateFromLocalStorage() {
  if (lsHydrated) return
  lsHydrated = true
  // sessions list 先読み (= オフラインでもとりあえず描画)
  const parsed = lsGet(LS_SESSIONS_META)
  if (Array.isArray(parsed) && parsed.length > 0) setSessions(parsed)
  // activeId 先読み (+ 旧 legacy key 掃除)
  try {
    const id = localStorage.getItem(LS_ACTIVE_SESSION)
    if (id) storeSetActiveId(id)
    if (localStorage.getItem(LS_LEGACY_ACTIVE_AGENT)) {
      localStorage.removeItem(LS_LEGACY_ACTIVE_AGENT)
    }
  } catch { /* ignore */ }
}

// 初回 useSessions 呼出時に同期で hydrate (= useState 初期化と同様、 1 frame 目から store
// に lsGet 結果を反映)。 module load 時にやらないのは lsGet 失敗時の例外が App 全体を
// 巻き込まないようにする保険 (= 旧 useState lazy 初期化と同方針)。
hydrateFromLocalStorage()

async function fetchBackendInitial() {
  if (backendInitRequested) return
  backendInitRequested = true
  try {
    const [serverSessions, serverAgents] = await Promise.all([
      apiFetch(`/sessions`).then(r => r.json()).catch(() => null),
      apiFetch(`/agents`).then(r => r.json()).catch(() => null),
    ])
    if (Array.isArray(serverAgents)) setAgents(serverAgents)
    if (Array.isArray(serverSessions)) {
      // 並び順: created_at 降順 (新しい順) で固定。 ChatGPT と同じく新規作成が一番上
      const sorted = [...serverSessions].sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
      setSessions(sorted)
      // active が backend に居ない or 未設定なら先頭 (= 一番新しい) に寄せる
      const cur = getSnapshot().activeId
      if (cur && sorted.some(s => s.id === cur)) {
        // keep
      } else {
        storeSetActiveId(sorted.length > 0 ? sorted[0].id : null)
      }
    }
  } catch {
    // 起動時 fetch 失敗 = localStorage 先読み結果で継続。 次回 retry は visibility 復帰系の
    // 別経路 (= status SSE / overview SSE) が拾うので、 本 hook では再試行しない。
    backendInitRequested = false  // retry 余地は残す (= 次 mount で再試行)
  }
}

// 以下、 mutation API は module-level の純関数 (= component instance に依存しない)。
// hook から useCallback でラップして返すが、 import して直呼出する path も許可する。

export async function createSession(agentId, accountId, title) {
  const body = { agent_id: agentId }
  if (accountId) body.account_id = accountId
  if (title) body.title = title
  let meta
  try {
    const res = await apiFetch(`/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    meta = await res.json()
  } catch (e) {
    // backend 不到達 / エラー: UI に通知して終了 (ローカルだけ作ると整合性崩れる)
    alert(`会話の作成に失敗しました: ${e?.message || e}`)
    return null
  }
  // 新しい順で並べたいので先頭に挿す
  appendSession(meta)
  storeSetActiveId(meta.id)
  return meta
}

// 会話を任意メッセージから分岐する (= フォーク)。 backend が lineage を新 jsonl に
// 書き出して子 SessionDef を返す → 先頭に挿して active を新タブへ。 元タブは無傷。
export async function forkSession(sourceId, fromUuid) {
  let meta
  try {
    const res = await apiFetch(`/sessions/${sourceId}/fork`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from_uuid: fromUuid }),
    })
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try { detail = (await res.json())?.detail || detail } catch { /* ignore */ }
      throw new Error(detail)
    }
    meta = await res.json()
  } catch (e) {
    alert(`フォークに失敗しました: ${e?.message || e}`)
    return null
  }
  appendSession(meta)
  storeSetActiveId(meta.id)
  return meta
}

export async function removeSession(id) {
  try {
    const r = await apiFetch(`/sessions/${id}`, { method: 'DELETE' })
    if (!r || !r.ok) {
      // backend に届かなかった or 拒否された場合は UI 上は消えても backend 側に session が
      // 残る (= 次回 /sessions GET で復活する「ゴーストタブ」)。 silent でなく console に
      // 残して、 ユーザは「消したのに戻ってきた」 を見て初めて気付くしかなかった状況を
      // 解消する (= 2026-06-22 silent-failure sweep)。

      console.warn('[sessions] delete failed:', id, r?.status)
    }
  } catch (e) {

    console.warn('[sessions] delete request errored:', id, e)
  }
  // 旧実装は setSessions / setActiveId の updater 内で同 tick 計算していた (= F-42)。
  // store API は値ベースなので getSnapshot で現状を読んで filter してから write する。
  const cur = getSnapshot()
  const next = cur.sessions.filter(s => s.id !== id)
  if (next.length !== cur.sessions.length) setSessions(next)
  if (cur.activeId === id) {
    storeSetActiveId(next.length > 0 ? next[0].id : null)
  }
}

export async function renameSession(id, title) {
  const trimmed = (title || '').trim()
  if (!trimmed) return
  // 楽観更新
  const cur = getSnapshot()
  setSessions(cur.sessions.map(s => s.id === id ? { ...s, title: trimmed } : s))
  try {
    const r = await apiFetch(`/sessions/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: trimmed }),
    })
    if (!r || !r.ok) {

      console.warn('[sessions] rename failed:', id, r?.status)
    }
  } catch (e) {

    console.warn('[sessions] rename request errored:', id, e)
  }
}

export async function setNotifyMode(id, mode) {
  // 楽観更新 (= ⋯ メニューの選択を即反映)
  const cur = getSnapshot()
  setSessions(cur.sessions.map(s => s.id === id ? { ...s, notify_mode: mode } : s))
  try {
    const r = await apiFetch(`/sessions/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notify_mode: mode }),
    })
    if (!r || !r.ok) {

      console.warn('[sessions] notify_mode set failed:', id, mode, r?.status)
    }
  } catch (e) {

    console.warn('[sessions] notify_mode set errored:', id, mode, e)
  }
}

export function setActiveId(sid) {
  storeSetActiveId(sid)
}

export function useSessions() {
  // store 直接 hydrate を hook 呼出側でも保証 (= module load 順に依存しない)
  hydrateFromLocalStorage()
  const snap = useSyncExternalStore(subscribe, getSnapshot)
  const { sessions, activeId, agents } = snap

  // localStorage 同期 (sessions / activeId が変わるたび)。 複数 instance で走っても無害
  // (= 同値書込で lsSet が同 string を上書き)。
  useEffect(() => {
    lsSet(LS_SESSIONS_META, sessions)
  }, [sessions])
  useEffect(() => {
    // 注: activeId が null になっても removeItem しない (= 次回起動で復元できるよう保持)。
    // 起動直後に sessions 取得前で一瞬 null になる経路があり、 そこで消すと次回 top fallback に落ちる。
    if (!activeId) return
    try { localStorage.setItem(LS_ACTIVE_SESSION, activeId) } catch { /* ignore */ }
  }, [activeId])

  // 起動時に backend の真値を取得して同期 (= module-level guard で 1 回限定)
  useEffect(() => {
    fetchBackendInitial()
  }, [])

  // 戻り値の関数は安定 identity で返す (= 旧 useCallback 互換、 ChatInput / MessageItem 等
  // の React.memo skip を維持)。
  const setActiveIdCb = useCallback((sid) => storeSetActiveId(sid), [])
  const createSessionCb = useCallback((agentId, accountId, title) => createSession(agentId, accountId, title), [])
  const forkSessionCb = useCallback((sourceId, fromUuid) => forkSession(sourceId, fromUuid), [])
  const removeSessionCb = useCallback((id) => removeSession(id), [])
  const renameSessionCb = useCallback((id, title) => renameSession(id, title), [])
  const setNotifyModeCb = useCallback((id, mode) => setNotifyMode(id, mode), [])

  return {
    sessions,
    activeId,
    setActiveId: setActiveIdCb,
    agents,
    createSession: createSessionCb,
    forkSession: forkSessionCb,
    removeSession: removeSessionCb,
    renameSession: renameSessionCb,
    setNotifyMode: setNotifyModeCb,
  }
}
