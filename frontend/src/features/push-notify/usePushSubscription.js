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
 *
 * J-2 (= 2026-06-29、 ADR-026 末尾「将来 task」 2 件目): hook 内 useState 4 個を撤廃 →
 * state/push.js singleton store + useSyncExternalStore に差し替え。 旧設計では AppEffects
 * と SessionDrawer の 2 経路で hook が並走し、 state が独立 instance に分裂 + 副作用
 * listener (= visibility / interval / SW broken) が全 instance で重複発火していた。
 * `mountEffects: true` で渡された 1 instance だけが listener を張る (= AppEffects 側を hub
 * 配置)、 他 instance は store subscribe + toggle 操作のみ。
 */
import { useEffect, useSyncExternalStore } from 'react'
import {
  enablePush,
  disablePush,
  isPushSupported,
  isStandalone,
  isMobileSafari,
  isPushEnabledLocally,
} from './push.js'
import {
  subscribe as subscribePush,
  getSnapshot as getPushSnapshot,
  setPushAvailable,
  setPushEnabled,
  setPushBroken,
  setPushBusy,
} from '../../state/push.js'

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
// VAPID 鍵生成 + subscribe を毎回走らせるので、 1 本だけに絞る。 J-2 で hook 多重 mount
// 問題は singleton store で解いたが、 本 guard は backend POST 重複抑止の最後の保険として残置。
let enableInflight = null
async function enablePushOnce() {
  if (enableInflight) return enableInflight
  enableInflight = (async () => {
    try { await enablePush() } finally { enableInflight = null }
  })()
  return enableInflight
}

function computeAvailable() {
  return isPushSupported() && (!isMobileSafari() || isStandalone())
}

// 現環境の available + 現在の localStorage フラグから enabled/broken を再計算して store に反映する。
// AppEffects 側 instance (= mountEffects:true) の sync 内で都度呼ばれる。
function applyStateFromEnvironment(hasRealSub) {
  const available = computeAvailable()
  const localFlag = isPushEnabledLocally()
  setPushAvailable(available)
  setPushEnabled(localFlag && hasRealSub)
  setPushBroken(localFlag && !hasRealSub && available)
}

/**
 * @param {object} [opts]
 * @param {() => void} [opts.onCloseMenu] toggle 時にメニューを閉じる callback (= SessionDrawer 用)
 * @param {boolean} [opts.mountEffects] true で副作用 listener (= visibility / interval / SW broken)
 *   を張る。 1 経路に集約するため AppEffects 側 1 instance のみ true で呼出、 他 (= SessionDrawer)
 *   は default = false で subscribe + toggle のみ。
 */
export function usePushSubscription({ onCloseMenu, mountEffects = false } = {}) {
  const snap = useSyncExternalStore(subscribePush, getPushSnapshot)

  // available は環境固定だが、 mountEffects=false 側でも初期表示前に store 反映しておく
  // (= SessionDrawer が AppEffects より先に render されるケースで `!pushAvailable` が
  // 一瞬 true になって UI が消えるのを避ける)。 同値 setter は store 内で no-op。
  useEffect(() => {
    setPushAvailable(computeAvailable())
  }, [])

  useEffect(() => {
    if (!mountEffects) return
    let cancelled = false
    let syncing = false
    const sync = async () => {
      // hidden 中は走らせない (= iOS PWA は bg suspended で実質止まる、 desktop は走るので明示 guard)
      if (document.hidden) return
      // 同 tick の二重起動を防ぐ (= setInterval と visibilitychange が同時に triggers するケース)
      if (syncing) return
      syncing = true
      try {
        const have = await detectActualSubscription()
        if (cancelled) return
        applyStateFromEnvironment(have)
        const available = computeAvailable()
        const curLocalFlag = isPushEnabledLocally()
        if (
          !have &&
          curLocalFlag &&
          available &&
          typeof Notification !== 'undefined' &&
          Notification.permission === 'granted'
        ) {
          try {
            await enablePushOnce()
            if (!cancelled) applyStateFromEnvironment(true)
          } catch (e) {
            // 次の 60s ping で再試行されるので silent でも回復はするが、 ずっと失敗してると
            // 通知が来ない状態が続く → 診断ログを残す (= 2026-06-22 silent-failure sweep)。

            console.warn('[push] enablePushOnce failed, will retry next ping:', e)
          }
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
    let swBrokenHandled = false
    const onSwMessage = (event) => {
      const d = event.data
      if (!d || d.type !== 'sw-broken') return
      if (swBrokenHandled) return
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
  }, [mountEffects])

  const handleTogglePush = async () => {
    if (getPushSnapshot().busy) return
    setPushBusy(true)
    onCloseMenu?.()
    try {
      if (getPushSnapshot().enabled) {
        await disablePush()
        applyStateFromEnvironment(false)
      } else {
        await enablePushOnce()
        applyStateFromEnvironment(true)
      }
    } catch (e) {
      alert(e?.message || '通知設定の変更に失敗しました')
    } finally {
      setPushBusy(false)
    }
  }

  return {
    pushAvailable: snap.available,
    pushEnabled: snap.enabled,
    pushBroken: snap.broken,
    pushBusy: snap.busy,
    handleTogglePush,
  }
}
