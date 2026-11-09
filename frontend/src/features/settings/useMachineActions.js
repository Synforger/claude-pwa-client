// 「この機械」 の 2 つの操作: アプリを更新する (= 画面を新しい build へ入れ替える) と、 backend を再起動する。
// 設定の画面を開いた時に、 backend が再起動できるか (= launchd の job として動いているか) と起動時刻を問い合わせる。
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiFetch } from '../../_common/api.js'
import { hardRefreshAppShell } from '../../_common/appRefresh.js'
import { runningBuildId } from '../../_common/appUpdate.js'

// backend の再起動後、 新しい backend が応答したかを問い合わせる間隔。
const RESTART_POLL_MS = 1000

/** → { runningBuild, refreshing, refreshApp, restartable, restartConfirm, setRestartConfirm, restarting,
 *       restartError, restart }。 */
export function useMachineActions() {
  const runningBuild = useMemo(() => runningBuildId(), [])
  const [refreshing, setRefreshing] = useState(false)
  const [restartable, setRestartable] = useState(false)
  const [restartConfirm, setRestartConfirm] = useState(false)
  const [restartError, setRestartError] = useState('')
  const [restarting, setRestarting] = useState(false)
  // 再起動前の backend の起動時刻。 これと違う値が返ったら新しい backend が応答している。
  const startedAtRef = useRef(null)

  useEffect(() => {
    const controller = new AbortController()
    apiFetch('/backend/restartable', { signal: controller.signal })
      .then(r => (r.ok ? r.json() : { restartable: false }))
      .then(body => {
        setRestartable(Boolean(body.restartable))
        startedAtRef.current = body.started_at ?? null
      })
      .catch(() => setRestartable(false))
    return () => controller.abort()
  }, [])

  // 画面を新しい build へ入れ替える (= 履歴・通知の許可は残す。 刷新の本体は _common/appRefresh.js)。
  const refreshApp = useCallback(async () => {
    setRefreshing(true)
    await hardRefreshAppShell()
  }, [])

  const restart = useCallback(async () => {
    setRestartConfirm(false)
    setRestartError('')
    try {
      const r = await apiFetch('/backend/restart', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: true }),
      })
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        setRestartError(body.detail || `HTTP ${r.status}`)
        return
      }
    } catch (e) {
      setRestartError(String(e?.message || e))
      return
    }
    setRestarting(true)
    // 新しい backend が応答するまで待ち、 アプリごと読み込み直す (= 「アプリを更新」 と同じ刷新なので、 backend と
    // 一緒に入った新しい画面もここで拾う)。 起動時刻を返さない backend からの入れ替えでは、 一度つながらなくなって
    // またつながったことを「戻った」 とする (= 止まる前の古い backend の応答と取り違えない)。
    const before = startedAtRef.current
    let wentDown = false
    for (;;) {
      await new Promise(resolve => setTimeout(resolve, RESTART_POLL_MS))
      try {
        const r = await apiFetch('/backend/restartable', { retry: 0 })
        if (!r.ok) { wentDown = true; continue }
        const body = await r.json()
        if (before != null ? body.started_at !== before : wentDown) break
      } catch {
        wentDown = true // 止まっている間は接続できない。 そのまま待つ。
      }
    }
    await hardRefreshAppShell()
  }, [])

  return { runningBuild, refreshing, refreshApp, restartable, restartConfirm, setRestartConfirm, restarting, restartError, restart }
}
