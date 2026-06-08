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

function pruneOldSessions(arr) {
  if (!Array.isArray(arr) || arr.length === 0) return arr
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
    const cleanArr = (arr) => arr.map(m => {
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
  }, [sessions])

  const msgSaveTimer = useRef(null)
  const inputSaveTimer = useRef(null)
  // sid → 前回 save した messages 参照 (== 同一参照なら dirty じゃない)。 React state の
  // setMessages(prev => ...) は変更のあった sid だけ新オブジェクトを返す設計 (= 既存) なので、
  // 参照比較で diff を取れる。
  const lastSavedRef = useRef({})

  // messages を localStorage に書く時は sid 別キー (v2) に分ける。 推論中の 1 sid だけ書き
  // 換える時に全 sid 分の JSON.stringify + 圧縮を回さなくて済む (= reviewer 指摘 #7)。
  useEffect(() => {
    if (msgSaveTimer.current) clearTimeout(msgSaveTimer.current)
    msgSaveTimer.current = setTimeout(() => {
      const runSave = () => {
        const sids = sessions.map(s => s.id)
        const liveSids = new Set(sids)
        // 削除済 sid の localStorage key を掃除 (= 永続化時に絞る、 元コメント通り)
        for (const sid of Object.keys(lastSavedRef.current)) {
          if (!liveSids.has(sid)) {
            try { localStorage.removeItem(v2Key(sid)) } catch { /* ignore */ }
            delete lastSavedRef.current[sid]
          }
        }
        for (const sid of sids) {
          const cur = messages[sid] || []
          // 参照比較で dirty 判定 (= sid に変更がなければ何もしない)
          if (lastSavedRef.current[sid] === cur) continue
          const pruned = pruneOldSessions(cur).slice(-MAX_MESSAGES)
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
      }
      // iOS Safari 18.4+ / Chrome / Firefox は requestIdleCallback あり。
      if (typeof window.requestIdleCallback === 'function') {
        window.requestIdleCallback(runSave, { timeout: 5000 })
      } else {
        runSave()
      }
    }, 1000)
  }, [messages, sessions])

  useEffect(() => {
    if (inputSaveTimer.current) clearTimeout(inputSaveTimer.current)
    // input は ChatInput タブ切替時にしか変わらない (= 打鍵中は ChatInput 内部 state)
    // なので発火頻度は低いが、 save 自体は idle 時に倒して描画と競合させない。
    const run = () => {
      const toSave = {}
      for (const s of sessions) {
        toSave[s.id] = input[s.id] || ''
      }
      try { localStorage.setItem(LS_INPUT, JSON.stringify(toSave)) } catch { /* ignore */ }
    }
    const ric = window.requestIdleCallback
    inputSaveTimer.current = setTimeout(() => {
      if (ric) ric(run, { timeout: 1500 })
      else run()
    }, 500)
  }, [input, sessions])

  return { messages, setMessages, input, setInput }
}
