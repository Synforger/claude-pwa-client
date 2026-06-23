import { useState, useRef, useEffect } from 'react'
import LZString from 'lz-string'
import { LEGACY_AGENT_TO_SESSION, LS_MESSAGES, LS_INPUT, MAX_MESSAGES } from '../constants.js'
import { generateId } from '../utils/id.js'

const { compressToUTF16, decompressFromUTF16 } = LZString

// sid 別キー prefix (v2)。 旧 LS_MESSAGES (= 全 sid を 1 keyに詰めた lz-string 圧縮) を
// 置き換える。 これにより推論中の sid 1 つだけ書き込む差分書込が可能になり、
// 全セッション分の JSON.stringify + 圧縮を毎回回さなくて済む。 旧 key は migration 後も
// しばらく残す (= rollback 安全弁)。
const LS_MESSAGES_V2_PREFIX = `${LS_MESSAGES}_v2_`
function v2Key(sid) { return LS_MESSAGES_V2_PREFIX + sid }

// 2026-06-24 server-of-truth 純化: localStorage 永続化境界の唯一の真値。 load (cleanArr) と
// save (runMsgSave) の両端で同関数を通すことで「user message は uuid 付き確定のみ persist」
// という制約を構造的に守る。 user 以外の role (agent / system) は通常通り通す。
// 詳細設計 = reconcileUserMessage.js 冒頭コメント参照。
export function isPersistableMessage(m) {
  if (!m) return false
  if (m.role === 'user') return !!m.uuid && !m.optimistic && !m.sendFailed
  return true
}

// 旧 agent_a / agent_b キーは「履歴を引き継がない方針」 になったので、 検出したら
// そのまま削除する (引き継ぎはしない)。
function dropLegacyKeys(obj) {
  if (!obj || typeof obj !== 'object') return obj
  const out = { ...obj }
  for (const legacyKey of Object.keys(LEGACY_AGENT_TO_SESSION)) {
    if (legacyKey in out) delete out[legacyKey]
  }
  return out
}

// 「セッション終了」 マーカー (= kind: 'session_end' の system メッセージ) を境界にして、
// 「現在進行中の会話 + 直前に終了した 1 セッションぶん」 だけ残す。
// マーカーが N 個以上あれば、 末尾から (KEEP_PREV_SESSIONS) 個目のマーカーより前を全部捨てる。
const KEEP_PREV_SESSIONS = 1 // 「1 個前の終了済みセッション」 まで保持

// quota 超過時に各 session の messages 先頭を切る割合 (= 10%)。 小さすぎると 10 回 retry で
// 解消せず、 大きすぎると保持メッセージが急減する。 10 回 × 10% = 累計 ~65% カット限度。
const QUOTA_RETRY_TRIM_RATIO = 0.1
const QUOTA_RETRY_MAX = 10

// 各 sid の「直近 session_end マーカー数」 を ref 保持して、 数が KEEP_PREV_SESSIONS + 1
// 未満なら線形走査をスキップする (= F-27)。 旧実装は save の度に sid 毎の全配列を走査
// していて非効率だった。 マーカーが少ない sid (= 大多数) は走査自体が空振り。
function countSessionEnds(arr) {
  if (!Array.isArray(arr)) return 0
  let n = 0
  for (let i = 0; i < arr.length; i++) {
    if (arr[i]?.role === 'system' && arr[i]?.kind === 'session_end') n++
  }
  return n
}

function pruneOldSessions(arr, knownEndCount) {
  if (!Array.isArray(arr) || arr.length === 0) return arr
  // マーカーが KEEP+1 未満なら削るものは無いので即 return (= F-27、 線形走査回避)
  const endCount = typeof knownEndCount === 'number' ? knownEndCount : countSessionEnds(arr)
  if (endCount < KEEP_PREV_SESSIONS + 1) return arr
  // 末尾から走査して N+1 個目のマーカーの位置を探す (= そこ以前を捨てる)
  // 例: KEEP_PREV_SESSIONS=1 なら、 末尾から 2 個目の session_end マーカーより前を捨てる
  const targetMarkerIndex = KEEP_PREV_SESSIONS + 1
  let found = 0
  let cutAt = -1
  for (let i = arr.length - 1; i >= 0; i--) {
    if (arr[i]?.role === 'system' && arr[i]?.kind === 'session_end') {
      found += 1
      if (found === targetMarkerIndex) {
        cutAt = i
        break
      }
    }
  }
  if (cutAt < 0) return arr // マーカーがそこまで無い = まだ削るほど履歴が無い
  return arr.slice(cutAt + 1)
}

// session_id をキーとして messages / input を localStorage と同期する。
// セッションが動的に増減するため、 dict は lazy init: 知らない session_id にアクセス
// した側 (useChatStream など) は空配列 / 空文字列を期待してよい。
export function useChatStorage(sessions) {
  const [messages, setMessages] = useState(() => {
    const cleanArr = (arr) => arr
      .filter(isPersistableMessage)
      .map(m => {
        const base = m.id ? m : { ...m, id: generateId() }
        if (base.askUserQuestion && !base.askUserQuestion.answered) {
          const { askUserQuestion: _drop, ...rest } = base
          return rest
        }
        return base
      })
    const result = {}
    // v2 (sid 別キー) を優先的に読む。 旧 LS_MESSAGES に居て v2 に居ない sid は migration として
    // result に取り込む (= 旧キーは消さない、 rollback 安全弁)。
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i)
        if (!k || !k.startsWith(LS_MESSAGES_V2_PREFIX)) continue
        const sid = k.slice(LS_MESSAGES_V2_PREFIX.length)
        try {
          const raw = localStorage.getItem(k)
          if (!raw) continue
          const decompressed = decompressFromUTF16(raw)
          const arr = decompressed ? JSON.parse(decompressed) : null
          if (Array.isArray(arr)) {
            result[sid] = pruneOldSessions(cleanArr(arr))
          }
        } catch { /* skip corrupt sid */ }
      }
    } catch { /* localStorage 不能環境 */ }
    // 旧 LS_MESSAGES からの migration (v2 にない sid のみ取り込み)
    try {
      const raw = localStorage.getItem(LS_MESSAGES)
      if (raw) {
        const decompressed = decompressFromUTF16(raw)
        let parsed = decompressed ? JSON.parse(decompressed) : JSON.parse(raw)
        parsed = dropLegacyKeys(parsed)
        if (parsed && typeof parsed === 'object') {
          for (const [sid, arr] of Object.entries(parsed)) {
            if (sid in result) continue // v2 が優先
            if (!Array.isArray(arr)) continue
            result[sid] = pruneOldSessions(cleanArr(arr))
          }
        }
      }
    } catch { /* ignored */ }
    return result
  })

  const [input, setInput] = useState(() => {
    try {
      const saved = localStorage.getItem(LS_INPUT)
      if (saved) {
        const parsed = dropLegacyKeys(JSON.parse(saved))
        if (parsed && typeof parsed === 'object') return parsed
      }
    } catch { /* ignore */ }
    return {}
  })

  // sessions が変わったタイミングで、 知らない session_id 用の空エントリを補う
  // (ない場合の `messages[sid]` アクセスを `[]` で安全に受けるため)
  //
  // F-28: 起動後に backend sessions list が初めて入ってきた時 (= sessions 初回非空)、
  // localStorage v2 key の中で backend に無い sid を即時 remove する。 旧実装は
  // 起動時に全 v2 key を decompress してメモリ展開していたので、 退役 session のデータが
  // 残り続けると起動コストが線形に膨らんでいた。 backend を真値として一度合流させれば
  // 起動時メモリも以後の save 対象もスリムになる。 1 度だけ実行 (= cleanupDoneRef)。
  useEffect(() => {
    setMessages(prev => {
      let changed = false
      const next = { ...prev }
      for (const s of sessions) {
        if (!(s.id in next)) { next[s.id] = []; changed = true }
      }
      // 削除されたセッションのキーは保持してもメモリ的に問題ない (永続化時に絞る)
      return changed ? next : prev
    })
    setInput(prev => {
      let changed = false
      const next = { ...prev }
      for (const s of sessions) {
        if (!(s.id in next)) { next[s.id] = ''; changed = true }
      }
      return changed ? next : prev
    })
    // backend list 突合 cleanup (= F-28、 1 回だけ)
    if (sessions.length > 0 && !cleanupDoneRef.current) {
      cleanupDoneRef.current = true
      const live = new Set(sessions.map(s => s.id))
      try {
        const toRemove = []
        for (let i = 0; i < localStorage.length; i++) {
          const k = localStorage.key(i)
          if (!k || !k.startsWith(LS_MESSAGES_V2_PREFIX)) continue
          const sid = k.slice(LS_MESSAGES_V2_PREFIX.length)
          if (!live.has(sid)) toRemove.push(k)
        }
        for (const k of toRemove) {
          try { localStorage.removeItem(k) } catch { /* ignore */ }
        }
        // 同時にメモリ側 messages からも消す (= save loop で残骸を見ない)
        if (toRemove.length > 0) {
          setMessages(prev => {
            const next = { ...prev }
            let changed = false
            for (const k of toRemove) {
              const sid = k.slice(LS_MESSAGES_V2_PREFIX.length)
              if (sid in next) { delete next[sid]; changed = true }
            }
            return changed ? next : prev
          })
        }
      } catch { /* localStorage 不能環境 */ }
    }
  }, [sessions])

  const msgSaveTimer = useRef(null)
  const inputSaveTimer = useRef(null)
  // sid → 前回 save した messages 参照 (== 同一参照なら dirty じゃない)。 React state の
  // setMessages(prev => ...) は変更のあった sid だけ新オブジェクトを返す設計 (= 既存) なので、
  // 参照比較で diff を取れる。
  const lastSavedRef = useRef({})
  // sid → 直近の session_end count (= F-27 の線形走査回避用キャッシュ)
  const endCountRef = useRef({})
  // backend sessions list との 1 回 cleanup 済みフラグ (= F-28)
  const cleanupDoneRef = useRef(false)

  // messages / input 保存ロジックを ref に逃がして、 debounce 経路 + pagehide / hidden 経路の
  // 両方から呼べるようにする (= 2026-06-22)。 旧実装は setTimeout 1s + requestIdleCallback の
  // 二段遅延 → iOS PWA をバックグラウンドにすると JS suspend で save が走らず、 戻った時に
  // 古いキャッシュが表示される事故源だった。
  const messagesRef = useRef(messages)
  const sessionsRef = useRef(sessions)
  const inputRef2 = useRef(input)
  useEffect(() => { messagesRef.current = messages }, [messages])
  useEffect(() => { sessionsRef.current = sessions }, [sessions])
  useEffect(() => { inputRef2.current = input }, [input])

  const runMsgSave = useRef(() => {
    const sids = sessionsRef.current.map(s => s.id)
    const liveSids = new Set(sids)
    const cur_messages = messagesRef.current
    // 削除済 sid の localStorage key を掃除 (= 永続化時に絞る、 元コメント通り)
    for (const sid of Object.keys(lastSavedRef.current)) {
      if (!liveSids.has(sid)) {
        try { localStorage.removeItem(v2Key(sid)) } catch { /* ignore */ }
        delete lastSavedRef.current[sid]
      }
    }
    for (const sid of sids) {
      const cur = cur_messages[sid] || []
      // 参照比較で dirty 判定 (= sid に変更がなければ何もしない)
      if (lastSavedRef.current[sid] === cur) continue
      const persistable = cur.filter(isPersistableMessage)
      // F-27: マーカー数を再計算 (= dirty な sid のみ)、 これを pruneOldSessions に渡す
      const endCount = countSessionEnds(persistable)
      endCountRef.current[sid] = endCount
      const pruned = pruneOldSessions(persistable, endCount).slice(-MAX_MESSAGES)
      // quota 超過時は古い方から N% ずつ削って再試行
      let toSave = pruned
      let saved = false
      for (let attempt = 0; attempt < QUOTA_RETRY_MAX; attempt++) {
        try {
          localStorage.setItem(v2Key(sid), compressToUTF16(JSON.stringify(toSave)))
          saved = true
          break
        } catch {
          if (toSave.length === 0) break
          const cut = Math.max(1, Math.floor(toSave.length * QUOTA_RETRY_TRIM_RATIO))
          toSave = toSave.slice(cut)
        }
      }
      if (saved) {
        lastSavedRef.current[sid] = cur
      } else {
        console.warn(`[chat-storage] quota exceeded for ${sid} after retries`)
      }
    }
  })

  const runInputSave = useRef(() => {
    const toSave = {}
    for (const s of sessionsRef.current) {
      toSave[s.id] = inputRef2.current[s.id] || ''
    }
    try { localStorage.setItem(LS_INPUT, JSON.stringify(toSave)) } catch { /* ignore */ }
  })

  // 通常経路 = setTimeout + requestIdleCallback で描画と競合させない遅延 save。
  // F-XX (= 2026-06-23): debounce を 1000ms → 250ms に短縮。 1s だと iOS PWA が bg に入った
  // タイミングで pending save を抱えたまま suspend / kill されることが頻発し、 復帰時に
  // 最大 1s 分の最新メッセージが失われていた。 250ms なら描画と競合しない範囲で
  // ほぼ即時 save、 失われ得る最大幅も 0.25s に圧縮できる (= 1 turn 分は確実に守れる)。
  useEffect(() => {
    if (msgSaveTimer.current) clearTimeout(msgSaveTimer.current)
    msgSaveTimer.current = setTimeout(() => {
      if (typeof window.requestIdleCallback === 'function') {
        window.requestIdleCallback(() => runMsgSave.current(), { timeout: 1000 })
      } else {
        runMsgSave.current()
      }
    }, 250)
  }, [messages, sessions])

  useEffect(() => {
    if (inputSaveTimer.current) clearTimeout(inputSaveTimer.current)
    const ric = window.requestIdleCallback
    inputSaveTimer.current = setTimeout(() => {
      if (ric) ric(() => runInputSave.current(), { timeout: 1500 })
      else runInputSave.current()
    }, 250)
  }, [input, sessions])

  // pagehide / freeze / visibilitychange-hidden で即時 flush (= 2026-06-23 iOS PWA bg 対策、
  // 旧 2026-06-22 修正の不足分):
  // - pagehide / beforeunload : 旧来からの suspend 直前イベント
  // - freeze                  : iOS 16+ で pagehide の前に / 代わりに発火するケースがあり
  //                              ここを取りこぼすと kill 時に最新キャッシュが落ちる
  // - visibilitychange→hidden : 確実な早期 trigger (= bg ボタンタップで即発火、 pagehide は
  //                              実際に画面が消えるまで待たれる場合がある)
  useEffect(() => {
    const flushAll = () => {
      if (msgSaveTimer.current) { clearTimeout(msgSaveTimer.current); msgSaveTimer.current = null }
      if (inputSaveTimer.current) { clearTimeout(inputSaveTimer.current); inputSaveTimer.current = null }
      try { runMsgSave.current() } catch { /* ignore */ }
      try { runInputSave.current() } catch { /* ignore */ }
    }
    const onVis = () => { if (document.visibilityState === 'hidden') flushAll() }
    window.addEventListener('pagehide', flushAll)
    window.addEventListener('beforeunload', flushAll)
    window.addEventListener('freeze', flushAll)
    document.addEventListener('visibilitychange', onVis)
    return () => {
      window.removeEventListener('pagehide', flushAll)
      window.removeEventListener('beforeunload', flushAll)
      window.removeEventListener('freeze', flushAll)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [])

  return { messages, setMessages, input, setInput }
}
