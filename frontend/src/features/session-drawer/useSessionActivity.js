// session ごとの「最終活動時刻」 を localStorage に永続化 + 並び順 sort 用。
// useAppEffects.js から物理移送 (= W2 Phase C、 session 一覧の表示属性)。
// W2 Phase E-2 (= 2026-06-29): 内部 useState → state/sessions.js sessionActivity field に集約。
// 永続化 useEffect は本 hook 内に残置 (= localStorage 書込責務は変えない)。
import { useEffect, useMemo, useRef, useSyncExternalStore } from 'react'
import { LS_SESSION_ACTIVITY } from '../../constants.js'
import { lsGet, lsSet } from '../../utils/storage.js'
import {
  subscribe as subscribeSessions,
  getSnapshot as getSessionsSnapshot,
  setSessionActivity,
} from '../../state/sessions.js'


// --- session ごとの「最終活動時刻」 を localStorage に永続化 + 並び順 sort 用 ---
// 値: { length: 直近の messages 件数, ts: その時の Date.now() }
// 永続値が無ければ ts=0 で記録 (= sort では created_at fallback)。

let lsHydrated = false
function hydrateFromLocalStorage() {
  if (lsHydrated) return
  lsHydrated = true
  const parsed = lsGet(LS_SESSION_ACTIVITY)
  if (parsed && typeof parsed === 'object') {
    for (const [sid, value] of Object.entries(parsed)) {
      setSessionActivity(sid, value)
    }
  }
}
hydrateFromLocalStorage()

export function useSessionActivity(messages, sessions) {
  // store 直接 hydrate (= module load 順に依存しない、 SSR 等の境界保護)
  hydrateFromLocalStorage()
  const snap = useSyncExternalStore(subscribeSessions, getSessionsSnapshot)
  const sessionActivity = snap.sessionActivity

  // messages dict は streaming flush で rAF 毎に新 reference になるが、 各 sid の
  // length が変化しない限りこの effect は走らせたくない。 length signature を計算して
  // dep にすることで、 reference 変化だけの再発火を抑える。
  const messagesLenSig = useMemo(
    () => Object.entries(messages).map(([sid, arr]) => `${sid}:${(arr || []).length}`).join('|'),
    [messages]
  )
  const messagesRef = useRef(messages)
  useEffect(() => { messagesRef.current = messages }, [messages])

  useEffect(() => {
    const cur = messagesRef.current
    const prev = getSessionsSnapshot().sessionActivity
    const now = Date.now()
    for (const sid of Object.keys(cur)) {
      const arr = cur[sid] || []
      const curEntry = prev[sid]
      if (!curEntry) {
        if (arr.length > 0) {
          setSessionActivity(sid, { length: arr.length, ts: 0 })
        }
        continue
      }
      if (arr.length > curEntry.length) {
        setSessionActivity(sid, { length: arr.length, ts: now })
      } else if (arr.length < curEntry.length) {
        setSessionActivity(sid, { length: arr.length, ts: curEntry.ts })
      }
    }
  }, [messagesLenSig])

  useEffect(() => {
    lsSet(LS_SESSION_ACTIVITY, sessionActivity)
  }, [sessionActivity])

  // sort された session 一覧 (= 「最終活動時刻」 降順、 0 や未活動は created_at fallback)。
  // sessions / sessionActivity が変わらない限り同じ array を返す (= SessionDrawer 等の
  // 下流が無駄に re-render しない)。
  const sortedSessions = useMemo(
    () => [...sessions].sort((a, b) => {
      const ta = (sessionActivity[a.id]?.ts) || ((a.created_at || 0) * 1000)
      const tb = (sessionActivity[b.id]?.ts) || ((b.created_at || 0) * 1000)
      return tb - ta
    }),
    [sessions, sessionActivity]
  )

  return { sessionActivity, sortedSessions }
}
