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
 * 楽観送信 (pendingSendRef): 送信直後は backend がまだ user 行を見ておらず busy=false の
 * ことがある。 その一瞬で停止ボタンが送信ボタンに戻る (= 二重送信・チラつき) のを防ぐため、
 * 送信時に pendingSendRef.current[sid] = {seen:false} を置き、 ここで確定的にクリアする:
 *   - busy=true を観測 = ターン開始確認 → クリアして以降 backend 権威に委譲
 *   - busy=false の snapshot を 2 回観測 = ターンが立ち上がらなかった (= 即終了 / no-op) →
 *     クリアして送信ボタンへ。 1 回目は保留 (= backend が user 行を処理する猶予)。
 * 旧来の 1500ms タイムアウト窓を撤去し、 snapshot 駆動の event ベースにした (= タイマーで
 * ボタンを駆動しない、 という参照実装の原則に合わせる)。
 *
 * 停止ボタン経路は backend に /views/ws で意思を送り、 backend が user_stopped を立てて
 * busy=false を強制 + 全 client に push するので、 frontend 側で別フラグは持たない。
 */
import { useEffect } from 'react'
import { apiUrl } from '../utils/api.js'
import { applyOverviewSnapshot } from './internal/applyOverviewSnapshot.js'

export function useSessionsOverview({ setLoading, pendingSendRef }) {
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
      setLoading(prev => applyOverviewSnapshot(prev, payload, pendingSendRef))
    }
    es.onerror = () => { /* EventSource は自動再接続 (= 一時切断は無視) */ }
    return () => es.close()
  }, [setLoading, pendingSendRef])
}
