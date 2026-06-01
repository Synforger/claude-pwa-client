/**
 * Web Push の購読状態 + 有効/無効トグル。
 *
 * pushAvailable は環境で固定 (= iOS は 16.4+ かつ standalone 必須等の制約)。
 * pushEnabled は **実 SW subscription の有無** を反映する (= localStorage の希望
 * フラグだけでなく、 端末側の PushSubscription が実在するかも確認)。 SW unregister
 * 等で subscription が黙って失効するケースを UI で隠さないため。
 * pushBroken = 希望フラグ ON だが実 subscription が無い (= 失効状態)、 UI で再有効化
 * を促す。
 * トグル中 (pushBusy) は連打防止。
 */
import { useEffect, useState } from 'react'
import {
  enablePush,
  disablePush,
  isPushSupported,
  isStandalone,
  isPushEnabledLocally,
} from '../utils/push.js'

async function detectActualSubscription() {
  try {
    if (!('serviceWorker' in navigator)) return false
    const reg = await navigator.serviceWorker.ready
    const sub = await reg.pushManager.getSubscription()
    return !!sub
  } catch {
    return false
  }
}

export function usePushSubscription({ onCloseMenu } = {}) {
  const [hasRealSub, setHasRealSub] = useState(false)
  const [pushBusy, setPushBusy] = useState(false)
  const pushAvailable = isPushSupported() && isStandalone()
  const localFlag = isPushEnabledLocally()

  // ON とみなすのは「希望 ON + 実 subscription あり」。 どちらかが欠けてれば実質 OFF。
  const pushEnabled = localFlag && hasRealSub
  // 希望 ON だが実 subscription が無い = 失効状態。 UI で再有効化を促す。
  const pushBroken = localFlag && !hasRealSub && pushAvailable

  // 起動時 + 復帰時に実 subscription の状態を反映 + 失効してたら自動修復を 1 回だけ試す。
  useEffect(() => {
    let cancelled = false
    let attemptedRepair = false
    const sync = async () => {
      const have = await detectActualSubscription()
      if (cancelled) return
      setHasRealSub(have)
      // 自動修復: 希望 ON で permission も granted、 でも sub が無い時に 1 回だけ
      // enablePush() を呼ぶ。 ユーザ操作なし (= permission ダイアログは既 granted なら出ない)。
      if (
        !have &&
        !attemptedRepair &&
        localFlag &&
        pushAvailable &&
        typeof Notification !== 'undefined' &&
        Notification.permission === 'granted'
      ) {
        attemptedRepair = true
        try {
          await enablePush()
          if (!cancelled) setHasRealSub(true)
        } catch { /* 失敗時は UI ボタンで手動再有効化 */ }
      }
    }
    sync()
    const onVis = () => { if (!document.hidden) sync() }
    document.addEventListener('visibilitychange', onVis)
    return () => { cancelled = true; document.removeEventListener('visibilitychange', onVis) }
  // localFlag / pushAvailable は実行中に変わらない前提 (= mount 時固定)。
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleTogglePush = async () => {
    if (pushBusy) return
    setPushBusy(true)
    onCloseMenu?.()
    try {
      if (pushEnabled) {
        await disablePush()
        setHasRealSub(false)
      } else {
        await enablePush()
        setHasRealSub(true)
      }
    } catch (e) {
      alert(e?.message || '通知設定の変更に失敗しました')
    } finally {
      setPushBusy(false)
    }
  }

  return { pushEnabled, pushBroken, pushBusy, pushAvailable, handleTogglePush }
}
