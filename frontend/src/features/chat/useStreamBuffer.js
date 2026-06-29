import { useRef } from 'react'
import { generateId } from '../../utils/id.js'

// SSE で飛んでくる細切れの assistant 更新 (text / thinking / tool_use) を、
// rAF で 1 フレームに 1 回だけ React state にコミットするためのバッファ。
// SDK は数十 ms 周期で更新を投げるので、setState を毎回呼ぶと再描画が詰まる。
//
// セッションごとに独立した buffer を持つ。 セッション (= session_id) は動的に
// 増減するので、 `bufFor(sid)` で lazy 初期化する。
//
// 公開関数:
// - bufFor(sid)                : 該当 sid の buf を取得 (= lazy 作成)、 直接 mutate する用
// - flushStreamBuf(sid)        : バッファを setState に反映
// - scheduleFlush(sid)         : rAF で 1 回だけ flush を予約
// - cancelAndFlush(sid)        : 予約をキャンセルして即 flush
// - resetBuf(sid)              : 新規ターン / reconnect 開始時の初期化
//
function emptyBuf() {
  return { text: null, thinking: null, newTools: [], needsNewBubble: false, uuid: null, dirty: false }
}

// messages 全長から uuid 一致 bubble を探す (= 末尾から逆走査で早期 return)。 見つから
// なければ -1 (= 新規 bubble として append)。
//
// 2026-06-30: 旧版は末尾 30 件のみ走査 (= UUID_LOOKUP_WINDOW)。 同 message.id の追加
// frame は時間近接なので末尾窓で十分という前提だったが、 backend `_initialize_sid_tail`
// を offset=0 化した stream-from-zero 設計 (= fork lineage 複製 / backend restart 復元
// / claude rotation 等で新 jsonl path 内の過去行を再 publish する) の下では、 historical
// な uuid が今 publish されて bubble 更新対象になるケースが出る。 末尾窓内に居ないと
// dedup 漏れで重複 append される。 MAX_MESSAGES=200 が上限なので逆走査全長でも実用は
// 軽い (= μs オーダー、 毎 rAF 200 走査の負荷は無視可)。 uuid は claude が割り当てる
// UUIDv4 で偶発衝突は確率ゼロ前提、 一致 = 同 bubble。
function findByUuid(msgs, uuid) {
  if (!uuid) return -1
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].uuid === uuid) return i
  }
  return -1
}

export function useStreamBuffer({ setMessages }) {
  // Map<sid, buf>。 dict 互換の proxy (= `streamBufRef.current[sid]`) を外向きに維持しつつ
  // 内部は Map で持つ (= F-02 趣旨の「Map 化」、 sid 出入りの多い長時間 session で
  // delete/in 検査を O(1) に明示)。
  const streamBufMap = useRef(new Map())
  const rafIdRef = useRef({})


  const bufFor = (sid) => {
    let buf = streamBufMap.current.get(sid)
    if (!buf) {
      buf = emptyBuf()
      streamBufMap.current.set(sid, buf)
    }
    return buf
  }

  const flushStreamBuf = (sid) => {
    const buf = streamBufMap.current.get(sid)
    if (!buf || !buf.dirty) return

    const snap = {
      text: buf.text,
      thinking: buf.thinking,
      newTools: [...buf.newTools],
      needsNewBubble: buf.needsNewBubble,
      uuid: buf.uuid,
    }
    buf.text = null
    buf.thinking = null
    buf.newTools = []
    buf.needsNewBubble = false
    buf.uuid = null
    buf.dirty = false

    setMessages(prev => {
      const cur = prev[sid] || []
      const msgs = [...cur]
      const last = msgs[msgs.length - 1]
      const lastIsEmptyAgent = last
        && last.role === 'agent'
        && last.streaming
        && !last.text
        && !last.thinking
        && (!last.tools || last.tools.length === 0)
        && !last.askUserQuestion

      if (snap.needsNewBubble) {
        // 同 uuid (= Anthropic message.id) の追加 frame と reconnect / replay 時の
        // 二重到着を兼用で吸収する。 JSONL は 1 つの assistant message を複数行に分けて
        // partial で書く (= tool_use を別行で追記する等) ので、 後から来たフレームの
        // content (= 新規 tool_use) を**既存 bubble に追記マージ**する。
        // 上書きでなくマージなのが重要: 旧実装は tools = [...snap.newTools] で
        // 既存 tool を消してた → multi-frame の 2 個目で 1 個目が消える bug。
        if (snap.uuid) {
          // 全長 (= MAX_MESSAGES 上限 200) から uuid 一致 bubble を末尾走査で探す。
          // 末尾近傍の追加 frame で早期 hit、 fork lineage / backend restart 復元で
          // historical な uuid が再 publish されても dedup 漏れなし (= 2026-06-30
          // stream-from-zero 設計の整合)。
          const existIdx = findByUuid(msgs, snap.uuid)
          if (existIdx >= 0) {
            const existing = msgs[existIdx]
            const existingTools = existing.tools || []
            const existingIds = new Set(existingTools.map(t => t.id))
            const addedTools = (snap.newTools || []).filter(t => !existingIds.has(t.id))
            msgs[existIdx] = {
              ...existing,
              // text / thinking は frame ごとに完全形で来るので、 非空なら新値、 空なら既存維持
              text: snap.text || existing.text || '',
              thinking: snap.thinking || existing.thinking || null,
              tools: addedTools.length > 0 ? [...existingTools, ...addedTools] : existingTools,
              streaming: existing.streaming,
            }
            return { ...prev, [sid]: msgs }
          }
        }
        // AssistantMessage 単位で 1 bubble。送信直後の空 streaming placeholder が
        // あればそこに今回の中身を埋めて推論中表示を消す。
        if (lastIsEmptyAgent) {
          msgs[msgs.length - 1] = {
            ...last,
            uuid: snap.uuid || last.uuid,
            text: snap.text || '',
            thinking: snap.thinking || null,
            tools: [...(snap.newTools || [])],
          }
          return { ...prev, [sid]: msgs }
        }
        return { ...prev, [sid]: [...msgs, {
          id: generateId(),
          uuid: snap.uuid || null,
          role: 'agent',
          text: snap.text || '',
          thinking: snap.thinking || null,
          tools: [...(snap.newTools || [])],
          streaming: true,
        }]}
      }

      // reconnect 再生など、既存バブルに積み増すパス
      if (!last || last.role !== 'agent') return prev
      const updated = { ...last }
      if (snap.text !== null) updated.text = snap.text
      if (snap.thinking !== null) updated.thinking = snap.thinking
      if (snap.newTools.length > 0) {
        const existing = updated.tools || []
        const existingIds = new Set(existing.map(t => t.id))
        const toAdd = snap.newTools.filter(t => !existingIds.has(t.id))
        if (toAdd.length > 0) updated.tools = [...existing, ...toAdd]
      }
      msgs[msgs.length - 1] = updated
      return { ...prev, [sid]: msgs }
    })
  }

  const scheduleFlush = (sid) => {
    if (rafIdRef.current[sid] != null) return
    rafIdRef.current[sid] = requestAnimationFrame(() => {
      rafIdRef.current[sid] = null
      flushStreamBuf(sid)
    })
  }

  const cancelAndFlush = (sid) => {
    if (rafIdRef.current[sid] != null) {
      cancelAnimationFrame(rafIdRef.current[sid])
      rafIdRef.current[sid] = null
    }
    flushStreamBuf(sid)
  }

  const resetBuf = (sid) => {
    streamBufMap.current.set(sid, emptyBuf())
  }

  return {
    flushStreamBuf,
    scheduleFlush,
    cancelAndFlush,
    resetBuf,
    bufFor,
  }
}
