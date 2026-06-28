/**
 * 全 session の busy 状態を 1 本の SSE (/sessions/overview/stream) で購読し、
 * loading[sid] を **backend 権威 busy の唯一のソース**として駆動する。
 *
 * 設計 (2026-06-03 根本治療): 停止ボタン (= loading) の真値は backend が JSONL の
 * stop_reason から確定的に算出した busy ただ 1 つ。 チャット SSE (useChatStream) は
 * loading を一切触らない (= 旧来の「per-tab assistant/result で loading を上下する」 +
 * 「overview で上書き」 の dual-driver を排除)。 overview は毎回フル snapshot なので、
 * イベント取りこぼし・再接続・複数デバイスでも、 次の snapshot で必ず正しい状態に収束する
 * (= reconcile-on-snapshot)。
 *
 * 楽観意図 (optimisticRef): 送信/停止 直後は backend がまだそれを処理しておらず、 逆向きの
 * busy が残った古い snapshot が来ることがある。 その一瞬でボタンが戻る (= 送信なら二重送信、
 * 停止なら「2 回押さないと送信に戻らない」) のを防ぐため、 操作時に want='busy'(送信) /
 * want='idle'(停止) を置き、 backend が追いつくまで保持する (詳細は applyOverviewSnapshot)。
 * 旧来の 1500ms タイムアウト窓を撤去し、 snapshot 駆動の event ベースにした (= タイマーで
 * ボタンを駆動しない、 という参照実装の原則に合わせる)。
 *
 * 停止ボタン経路は backend に /views/ws で意思を送り、 backend が user_stopped を立てて
 * busy=false を強制 + 全 client に push するので、 frontend 側で別フラグは持たない。
 */
import { useEffect, useRef } from 'react'
import { applyOverviewSnapshot } from './applyOverviewSnapshot.js'
import { registerConnection, notifyConnectionChange } from '../../transport/connectionStatus.js'
import { sessionsOverviewSse } from '../../transport/sse-sessions-overview.ts'

export function useSessionsOverview({ setLoading, optimisticRef, onPayloadRef }) {
  const liveRef = useRef(false)
  useEffect(() => {
    // /sessions/overview/stream は transport/sse-sessions-overview.ts singleton が所有 (= ADR-019)。
    // ここは subscribe するだけ、 EventSource lifecycle / 再接続 / state は transport 側で扱う。
    const unreg = registerConnection(() => liveRef.current)
    const unsub = sessionsOverviewSse.subscribe(payload => {
      liveRef.current = true
      notifyConnectionChange()
      setLoading(prev => applyOverviewSnapshot(prev, payload, optimisticRef))
      // last_seen_at 等の追加 field を別 hook に流すための副経路 (= 未読同期、 2026-06-10 追加)。
      if (onPayloadRef?.current) onPayloadRef.current(payload)
    })
    return () => { unreg(); unsub(); liveRef.current = false }
  }, [setLoading, optimisticRef, onPayloadRef])
}
