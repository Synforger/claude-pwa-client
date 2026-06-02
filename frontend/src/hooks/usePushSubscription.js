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

  // 実 subscription の状態を「mount + visibility 復帰 + 1 分おき」 で同期 + 失効してたら
  // 毎回自動修復を試す。 iOS Safari は長時間放置で PushSubscription を OS が破棄する
  // ことがあるので、 visibility 復帰を待たず裏で先回り修復してユーザに「⚠失効」 を
  // 見せない。 enablePush は idempotent (= 同 endpoint なら backend で upsert)。
  useEffect(() => {
    let cancelled = false
    const sync = async () => {
      const have = await detectActualSubscription()
      if (cancelled) return
      setHasRealSub(have)
      if (
        !have &&
        localFlag &&
        pushAvailable &&
        typeof Notification !== 'undefined' &&
        Notification.permission === 'granted'
      ) {
        try {
          await enablePush()
          if (!cancelled) setHasRealSub(true)
        } catch { /* 失敗時は次の ping で再試行 */ }
      }
    }
    sync()
    const onVis = () => { if (!document.hidden) sync() }
    document.addEventListener('visibilitychange', onVis)
    const intervalId = setInterval(sync, 60_000)
    return () => {
      cancelled = true
      document.removeEventListener('visibilitychange', onVis)
      clearInterval(intervalId)
    }
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
