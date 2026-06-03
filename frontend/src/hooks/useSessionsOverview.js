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
import { useEffect } from 'react'
import { apiUrl } from '../utils/api.js'
import { applyOverviewSnapshot } from './internal/applyOverviewSnapshot.js'

export function useSessionsOverview({ setLoading, optimisticRef }) {
  useEffect(() => {
    const es = new EventSource(apiUrl('/sessions/overview/stream'))
    es.onmessage = (e) => {
      if (!e.data) return
      let payload
      try {
        payload = JSON.parse(e.data)
      } catch {
        return
      }
      setLoading(prev => applyOverviewSnapshot(prev, payload, optimisticRef))
    }
    es.onerror = () => { /* EventSource は自動再接続 (= 一時切断は無視) */ }
    return () => es.close()
  }, [setLoading, optimisticRef])
}
