import { useCallback, useEffect, useRef, useState } from 'react'
import {
  LS_ACTIVE_SESSION,
  LS_LEGACY_ACTIVE_AGENT,
  LS_SESSIONS_META,
} from '../constants.js'
import { apiFetch } from '../utils/api.js'
import { lsGet, lsSet } from '../utils/storage.js'

// セッション (= UI 上の 1 タブ = 1 議題) のリストと、 現在 active な session_id を管理する。
// backend `/sessions` を真値とし、 起動時に GET でローカルの localStorage と同期する。
// ローカル先読みでオフライン時の表示を維持しつつ、 ネットワーク復帰時に backend を信頼する。
export function useSessions() {
  // 起動時は localStorage から先読み (オフラインでもとりあえず描画する)
  const [sessions, setSessions] = useState(() => {
    const parsed = lsGet(LS_SESSIONS_META)
    return Array.isArray(parsed) ? parsed : []
  })

  const [activeId, setActiveId] = useState(() => {
    try {
      const id = localStorage.getItem(LS_ACTIVE_SESSION)
      if (id) return id
      // 旧 cpc_active_agent はもう移行しない方針。 残ってたら掃除だけする
      if (localStorage.getItem(LS_LEGACY_ACTIVE_AGENT)) {
        localStorage.removeItem(LS_LEGACY_ACTIVE_AGENT)
      }
    } catch { /* ignore */ }
    return null
  })

  const [agents, setAgents] = useState([]) // 作成時の選択肢 (backend 設定済 agent 一覧)
  const initRef = useRef(false)

  // localStorage 同期 (sessions / activeId が変わるたび)
  useEffect(() => {
    lsSet(LS_SESSIONS_META, sessions)
  }, [sessions])
  useEffect(() => {
    try {
      if (activeId) localStorage.setItem(LS_ACTIVE_SESSION, activeId)
      else localStorage.removeItem(LS_ACTIVE_SESSION)
    } catch { /* ignore */ }
  }, [activeId])

  // 起動時に backend の真値を取得して同期
  useEffect(() => {
    if (initRef.current) return
    initRef.current = true
    Promise.all([
      apiFetch(`/sessions`).then(r => r.json()).catch(() => null),
      apiFetch(`/agents`).then(r => r.json()).catch(() => null),
    ]).then(([serverSessions, serverAgents]) => {
      if (Array.isArray(serverAgents)) setAgents(serverAgents)
      if (Array.isArray(serverSessions)) {
        // 並び順: created_at 降順 (新しい順) で固定。 ChatGPT と同じく新規作成が一番上
        const sorted = [...serverSessions].sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
        setSessions(sorted)
        // active が backend に居ない or 未設定なら先頭 (= 一番新しい) に寄せる
        setActiveId(prev => {
          if (prev && sorted.some(s => s.id === prev)) return prev
          return sorted.length > 0 ? sorted[0].id : null
        })
      }
    })
  }, [])

  const createSession = useCallback(async (agentId, accountId, title) => {
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
    setSessions(prev => [meta, ...prev])
    setActiveId(meta.id)
    return meta
  }, [])

  // 会話を任意メッセージから分岐する (= フォーク)。 backend が lineage を新 jsonl に
  // 書き出して子 SessionDef を返す → 先頭に挿して active を新タブへ。 元タブは無傷。
  const forkSession = useCallback(async (sourceId, fromUuid) => {
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
    setSessions(prev => [meta, ...prev])
    setActiveId(meta.id)
    return meta
  }, [])

  const removeSession = useCallback(async (id) => {
    try {
      await apiFetch(`/sessions/${id}`, { method: 'DELETE' })
    } catch { /* backend 未到達でもローカル状態は消す */ }
    // 現在の sessions / activeId を直接読んで外で計算する (updater 内に副作用を持たない)。
    // React の StrictMode で updater が 2 回実行されても安全。
    const wasActive = sessions.some(s => s.id === id) && activeId === id
    const nextSessions = sessions.filter(s => s.id !== id)
    setSessions(nextSessions)
    if (wasActive) {
      setActiveId(nextSessions.length > 0 ? nextSessions[0].id : null)
    }
  }, [sessions, activeId])

  const renameSession = useCallback(async (id, title) => {
    const trimmed = (title || '').trim()
    if (!trimmed) return
    // 楽観更新
    setSessions(prev => prev.map(s => s.id === id ? { ...s, title: trimmed } : s))
    try {
      await apiFetch(`/sessions/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: trimmed }),
      })
    } catch { /* ignore: ローカルは既に反映済み */ }
  }, [])

  const setNotifyMode = useCallback(async (id, mode) => {
    // 楽観更新 (= ⋯ メニューの選択を即反映)
    setSessions(prev => prev.map(s => s.id === id ? { ...s, notify_mode: mode } : s))
    try {
      await apiFetch(`/sessions/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notify_mode: mode }),
      })
    } catch { /* ignore: ローカルは既に反映済み */ }
  }, [])

  return {
    sessions,
    activeId,
    setActiveId,
    agents,
    createSession,
    forkSession,
    removeSession,
    renameSession,
    setNotifyMode,
  }
}
