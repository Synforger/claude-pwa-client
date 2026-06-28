// session ごとの新着 / 処理中 / 質問待ちバッジ計算 + app badge 連動。
// useAppEffects.js から物理移送 (= W2 Phase C、 push 通知系の責務をここに寄せる)。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiFetch } from '../../utils/api.js'
import { lsGet, lsSetDebounced } from '../../utils/storage.js'


// --- session ごとの新着 / 処理中 / 質問待ちバッジ計算 ---
// バッジは停止/送信ボタンの状態と 1:1 同期する (= 2026-05-29 改定):
//   - loading[sid] === true (= 停止ボタン中) → 青丸 (processing)
//   - loading[sid] が true→false に遷移 (= 送信解禁、 turn 完了) → 赤丸 (new)
//   - active タブで赤丸を見たら解除
// 旧仕様の `arr.length > lastSeen` は使わない: streaming 中の length 変動や JSONL flush の
// 順序揺らぎを噛むより、 loading 解除の 1 イベントで「返信きた」 を確定する方が体感に合う。
// 「turn 完了で未閲覧」 を localStorage に永続化 (= リロード跨ぎで赤を保持)。
const LS_UNREAD_DONE = 'cpc.unreadDone'

// 旧バッジ仕様 (= `arr.length > lastSeen`) の orphan key を 1 回だけ掃除する。
try { localStorage.removeItem('cpc.lastSeenLen') } catch { /* storage 無効環境は無視 */ }

function loadUnreadDone() {
  const parsed = lsGet(LS_UNREAD_DONE)
  return parsed && typeof parsed === 'object' ? parsed : {}
}

export function useSessionBadges({ sids, activeSid, messages, loading }) {
  // sid → true なら「turn 完了して未閲覧」
  const [unreadDone, setUnreadDone] = useState(loadUnreadDone)
  // 前回 render 時の loading[sid]。 true→false 遷移検出用。
  const prevLoadingRef = useRef({})
  // 自端末がこの sid を最後に見た時刻 (unix sec)。 overview の last_seen_at と比較して
  // 「他端末で自分より後に見られたか」 を判定する。 揮発で OK (= ページ更新で初期化、
  // 新たに開く時点で activeSid useEffect が即 POST + 自分の lastSeenLocallyRef も更新)。
  const lastSeenLocallyRef = useRef({})
  // 起動直後の settle gate。 初回 overview payload を 1 回受信するまで loading 遷移
  // から赤丸化しない (= F-13)。 旧 1500ms 固定では backend 起動遅延で payload が 1.5s
  // 以上来なかった時に誤判定する可能性があった。 「初回 payload 受信」 は
  // onOverviewPayload が必ず呼ばれる経路 (= useSessionsOverview 経由) なので確実な signal。
  const bootSettledRef = useRef(false)

  // messages の最新 ref (= pending question 判定用)
  const messagesRef = useRef(messages)
  useEffect(() => { messagesRef.current = messages }, [messages])

  // localStorage 永続化。 unreadDone は loading 遷移 / activeSid 切替で短時間に連発する
  // ため debounce (= F-46)。 中間 value は捨てて末尾 1 回だけ書く。
  useEffect(() => {
    lsSetDebounced(LS_UNREAD_DONE, unreadDone)
  }, [unreadDone])

  // 明示的既読化: session click 時に呼ばれる。 activeSid useEffect の前に
  // sync で赤丸を落とせる経路。
  const markAsSeen = useCallback((sid) => {
    if (!sid) return
    setUnreadDone(prev => (prev[sid] ? { ...prev, [sid]: false } : prev))
  }, [])

  // loading[sid] が true→false に変化した sid を unreadDone=true でマーク。
  // 同時に active タブの sid は積み立てずスキップ (= 見ている最中の完了は赤化不要)。
  useEffect(() => {
    const prev = prevLoadingRef.current
    const next = {}
    let mutated = false
    const flips = []
    for (const sid of sids) {
      const wasLoading = !!prev[sid]
      const isLoading = !!loading[sid]
      next[sid] = isLoading
      if (wasLoading && !isLoading && sid !== activeSid) {
        flips.push(sid)
      }
    }
    prevLoadingRef.current = next
    // boot settle: 初回 overview payload を受けるまで赤化しない (= F-13)。
    if (!bootSettledRef.current) return
    if (flips.length === 0) return
    setUnreadDone(p => {
      const out = { ...p }
      for (const sid of flips) {
        if (!out[sid]) { out[sid] = true; mutated = true }
      }
      return mutated ? out : p
    })
  }, [sids, loading, activeSid])

  // active タブに切替 / active タブの状態が動いた時に赤丸を落とす + backend に「見た」 を POST。
  // POST で他端末の赤丸も同期消去される (= overview SSE で last_seen_at を broadcast)。
  //
  // 高速切替時の POST 連発を防ぐため 150ms debounce (= F-21、 F-20 と同方針)。
  // local 状態 (= 赤丸消す / lastSeenLocally 更新) は即時、 backend POST だけ末尾 1 回。
  useEffect(() => {
    if (!activeSid) return
    setUnreadDone(prev => (prev[activeSid] ? { ...prev, [activeSid]: false } : prev))
    // 自端末の「最後に見た時刻」 を local に記録 → overview の last_seen_at と比較する基準。
    lastSeenLocallyRef.current[activeSid] = Date.now() / 1000
    const timer = setTimeout(() => {
      // backend に「見た」 を投げる (= ack されたら他端末の SSE で last_seen_at が更新される)。
      apiFetch(`/sessions/${encodeURIComponent(activeSid)}/seen`, { method: 'POST' }).catch(() => {})
    }, 150)
    return () => clearTimeout(timer)
  }, [activeSid])

  // overview SSE で受信した last_seen_at を見て、 「他端末で自分より後に見られた sid」 の
  // unreadDone を消す。 これで iPhone と Mac で開いたタブの赤丸が同期する。
  //
  // 初回 payload 受信で boot settle (= F-13)。 以後 loading 遷移は赤化反映される。
  const onOverviewPayload = useCallback((payload) => {
    if (!payload || typeof payload !== 'object') return
    bootSettledRef.current = true
    setUnreadDone(prev => {
      let mutated = false
      const next = { ...prev }
      for (const [sid, info] of Object.entries(payload)) {
        const remote = info?.last_seen_at
        if (typeof remote !== 'number') continue
        const local = lastSeenLocallyRef.current[sid] || 0
        // 他端末の last_seen_at が自分の最後の閲覧より新しい = 他端末で確認された → 赤丸消す
        if (remote > local && next[sid]) {
          next[sid] = false
          mutated = true
        }
      }
      return mutated ? next : prev
    })
  }, [])

  // 削除された session のエントリ掃除。
  useEffect(() => {
    setUnreadDone(prev => {
      const sidSet = new Set(sids)
      const next = { ...prev }
      let changed = false
      for (const k of Object.keys(next)) {
        if (!sidSet.has(k)) { delete next[k]; changed = true }
      }
      return changed ? next : prev
    })
  }, [sids])

  // 表示状態 signature: pending question 有無 + loading 状態 + unreadDone。
  const sessionStateSig = useMemo(
    () => sids.map(sid => {
      const arr = messages[sid] || []
      const pending = arr.some(m => m.askUserQuestion && !m.askUserQuestion.answered)
      return `${sid}:${pending ? 'p' : ''}:${loading[sid] ? 'l' : ''}:${unreadDone[sid] ? 'n' : ''}`
    }).join('|'),
    [sids, messages, loading, unreadDone]
  )

  // sessionBadges / unreadCount: signature が同じ間は同じ object を返す。
  // unreadCount はアプリバッジ数字 = 赤丸が立った session 数。
  const { sessionBadges, unreadCount } = useMemo(() => {
    const cur = messagesRef.current
    const badges = {}
    let count = 0
    for (const sid of sids) {
      if (sid === activeSid) { badges[sid] = null; continue }
      const arr = cur[sid] || []
      const pending = arr.some(m => m.askUserQuestion && !m.askUserQuestion.answered)
      if (pending) { badges[sid] = { kind: 'pending', label: '?' }; continue }
      if (loading[sid]) { badges[sid] = { kind: 'processing', label: '●' }; continue }
      if (unreadDone[sid]) { badges[sid] = { kind: 'new', label: '●' }; count++; continue }
      badges[sid] = null
    }
    return { sessionBadges: badges, unreadCount: count }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSid, sessionStateSig])
  return { sessionBadges, unreadCount, markAsSeen, onOverviewPayload }
}
