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
 *
 * F-17 (= 2026-06-21): 旧設計では App.jsx 側でも backend 再起動検出時に enablePush() を
 * 呼んでいたため、 visibility 復帰 / interval / App.jsx 側 + 3 経路が並列で enablePush
 * を叩くケースがあった (= backend が同 endpoint を upsert 受けるので最終結果は正しいが、
 * 不要な network round trip と subscription churn を生む)。 enablePush 一元化を本 hook
 * に集約 + module-level の inflight guard で「同時実行は 1 本だけ」 を保証する。
 *
 * F-18 (= 2026-06-21): 旧 localFlag は mount 時の closure 値を hold していたため、
 * 他タブで利用者が enable / disable した変化が visibility 復帰時に反映されなかった。
 * sync 関数内で都度 isPushEnabledLocally() を呼んで最新値を読み直す。
 *
 * F-19 (= 2026-06-21): sw.js が showNotification 失効を検出した時に postMessage で
 * 'sw-broken' を送ってくる。 受信したら本 hook が SW を unregister + reload して
 * 確実に新しい registration を取り直す (= 失効が起きた SW を構造的に捨てる)。
 */
import { useEffect, useState } from 'react'
import {
  enablePush,
  disablePush,
  isPushSupported,
  isStandalone,
  isMobileSafari,
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

// module-level inflight guard。 enablePush は backend で idempotent upsert されるが、
// 並列で 3 経路 (= mount / visibility 復帰 / interval) から同時に呼ばれると無駄な
// VAPID 鍵生成 + subscribe を毎回走らせるので、 1 本だけに絞る。
let enableInflight = null
async function enablePushOnce() {
  if (enableInflight) return enableInflight
  enableInflight = (async () => {
    try { await enablePush() } finally { enableInflight = null }
  })()
  return enableInflight
}

export function usePushSubscription({ onCloseMenu } = {}) {
  const [hasRealSub, setHasRealSub] = useState(false)
  const [pushBusy, setPushBusy] = useState(false)
  // localFlag は他タブで動く可能性があるため state 化、 sync 内で常に最新値を読み直す。
  const [localFlag, setLocalFlag] = useState(() => isPushEnabledLocally())
  // standalone 必須は iOS / iPadOS Safari の制約のみ。 デスクトップ Safari / Chrome は
  // 通常タブで OK (= 詳細は utils/push.js 冒頭)。
  const pushAvailable = isPushSupported() && (!isMobileSafari() || isStandalone())

  // ON とみなすのは「希望 ON + 実 subscription あり」。 どちらかが欠けてれば実質 OFF。
  const pushEnabled = localFlag && hasRealSub
  // 希望 ON だが実 subscription が無い = 失効状態。 UI で再有効化を促す。
  const pushBroken = localFlag && !hasRealSub && pushAvailable

  // 実 subscription の状態を「mount + visibility 復帰 + 1 分おき」 で同期 + 失効してたら
  // 毎回自動修復を試す。 iOS Safari は長時間放置で PushSubscription を OS が破棄する
  // ことがあるので、 visibility 復帰を待たず裏で先回り修復してユーザに「⚠失効」 を
  // 見せない。 enablePushOnce は module-level guard で多重起動を抑える (= F-17)。
  useEffect(() => {
    let cancelled = false
    let syncing = false
    const sync = async () => {
      // hidden 中は走らせない (= iOS PWA は bg suspended で実質止まる、 desktop は走るので明示 guard)
      if (document.hidden) return
      // 同 tick の二重起動を防ぐ (= setInterval と visibilitychange が同時に triggers するケース)
      if (syncing) return
      syncing = true
      try {
        // F-18: 都度 localStorage を読み直す (= 他タブで変化した可能性に追従)
        const curLocalFlag = isPushEnabledLocally()
        setLocalFlag(curLocalFlag)
        const have = await detectActualSubscription()
        if (cancelled) return
        setHasRealSub(have)
        if (
          !have &&
          curLocalFlag &&
          pushAvailable &&
          typeof Notification !== 'undefined' &&
          Notification.permission === 'granted'
        ) {
          try {
            await enablePushOnce()
            if (!cancelled) setHasRealSub(true)
          } catch { /* 失敗時は次の ping で再試行 */ }
        }
      } finally {
        syncing = false
      }
    }
    sync()
    const onVis = () => { if (!document.hidden) sync() }
    document.addEventListener('visibilitychange', onVis)
    const intervalId = setInterval(sync, 60_000)

    // F-19: sw.js から「showNotification 失効を検出」 の postMessage が来たら、
    // SW を unregister + reload で確実に新規 registration を取得し直す。
    // 旧設計では sw.js 内 diagLog だけで止まっていて、 失効した SW がそのまま居座って
    // 3 回 silent push 連続 → OS による PushSubscription 強制破棄、 という事故ルートを
    // 残していた。 unregister + reload で SW lifecycle をリセットすれば確実に治る。
    let swBrokenHandled = false
    const onSwMessage = (event) => {
      const d = event.data
      if (!d || d.type !== 'sw-broken') return
      if (swBrokenHandled) return // 同 page で 2 回走らせない
      swBrokenHandled = true
      ;(async () => {
        try {
          if ('serviceWorker' in navigator) {
            const regs = await navigator.serviceWorker.getRegistrations()
            for (const r of regs) {
              try { await r.unregister() } catch { /* ignore */ }
            }
          }
        } catch { /* ignore */ }
        // 完全リロードで新 SW を再 install。 visibility 中だけ実行 (= hidden だと
        // iOS が処理しない可能性、 復帰時に再 trigger)。
        if (!document.hidden) {
          try { window.location.reload() } catch { /* ignore */ }
        }
      })()
    }
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.addEventListener('message', onSwMessage)
    }

    return () => {
      cancelled = true
      document.removeEventListener('visibilitychange', onVis)
      clearInterval(intervalId)
      if ('serviceWorker' in navigator) {
        navigator.serviceWorker.removeEventListener('message', onSwMessage)
      }
    }
  // pushAvailable は実行中に変わらない前提 (= mount 時固定)。
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
        setLocalFlag(isPushEnabledLocally())
      } else {
        await enablePushOnce()
        setHasRealSub(true)
        setLocalFlag(isPushEnabledLocally())
      }
    } catch (e) {
      alert(e?.message || '通知設定の変更に失敗しました')
    } finally {
      setPushBusy(false)
    }
  }

  return { pushEnabled, pushBroken, pushBusy, pushAvailable, handleTogglePush }
}
