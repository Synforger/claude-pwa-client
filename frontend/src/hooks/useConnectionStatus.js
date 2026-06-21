/**
 * 全 SSE / WS の生死を集約して「オンライン / オフライン」 を返す hook (= F-45)。
 *
 * 設計:
 *   - 個別 hook (= useStatus / useSessionsOverview / useViewsWs 等) が自分の readyState を
 *     report する形ではなく、 module-level の `connectionRegistry` に各接続が自身を
 *     register / unregister する pull モデル。 各 hook 側は最小限の wire (= 1 関数呼ぶだけ)
 *     で済む。
 *   - 集約は「全接続のうち 1 本でも open ならオンライン、 全部 closed / connecting なら
 *     オフライン」 (= 完全オフラインだけを警告。 部分劣化は表示しない方針、 1 本でも
 *     生きてれば backend は到達可能)。
 *   - 接続が 1 本も register されてない場合は **不明扱い = true** (= 起動直後の race で
 *     誤って ⚠ オフラインを瞬間表示しない)。
 *
 * 使い方:
 *   - 接続側: `const unreg = registerConnection(() => ws.readyState === WebSocket.OPEN); ... unreg()`
 *   - StatusBar 側 (= W2-D 担当): `const isOnline = useConnectionStatus()` で chip 表示
 *
 * 評価は subscriber 通知駆動 (= 各接続側で `notifyConnectionChange()` を呼ぶ)。
 * 受動的 polling は使わない (= 状態が変わる時は接続側が必ず知っている)。
 */
import { useEffect, useState } from 'react'

// connection id (= number) -> isOpen 評価関数。 各接続側で 1 つ持つ。
const connectionRegistry = new Map()
let nextConnId = 1
const subscribers = new Set()

function evaluate() {
  if (connectionRegistry.size === 0) return true // 不明 = online 扱い
  for (const probe of connectionRegistry.values()) {
    try { if (probe()) return true } catch { /* ignore */ }
  }
  return false
}

function notifyAll() {
  for (const fn of subscribers) {
    try { fn() } catch { /* ignore */ }
  }
}

/**
 * 接続を registry に追加。 probe は `() => boolean` (= 現在 open か)。
 * 返り値の unregister を unmount で必ず呼ぶこと。
 */
export function registerConnection(probe) {
  const id = nextConnId++
  connectionRegistry.set(id, probe)
  notifyAll()
  return () => {
    connectionRegistry.delete(id)
    notifyAll()
  }
}

/**
 * 接続側が readyState を変えた時 (= onopen / onclose 等) に呼ぶ。 subscriber を再評価。
 */
export function notifyConnectionChange() {
  notifyAll()
}

export function useConnectionStatus() {
  const [isOnline, setIsOnline] = useState(evaluate)
  useEffect(() => {
    const update = () => setIsOnline(evaluate())
    subscribers.add(update)
    // mount 時に最新値で同期 (= subscribe より前に状態が動いてた race を吸収)
    update()
    return () => { subscribers.delete(update) }
  }, [])
  return isOnline
}

// test 用
export function __resetConnectionRegistry() {
  connectionRegistry.clear()
  subscribers.clear()
  nextConnId = 1
}
