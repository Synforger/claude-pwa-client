// 設定の画面の値を持つ hook: 開いた時に読み、 変えた時と続けた時に読み直す。
import { useCallback, useEffect, useRef, useState } from 'react'
import { continueAccount, fetchSettings, updateSettings } from './settingsApi.js'

/** → { view, loadedAt, error, save(patch), continueTabs(account), reload() }。 view = null の間は読み込み中。
 *  loadedAt = view を受け取った時刻 (epoch 秒。 戻る時刻が過ぎたかと今日の曜日を、 描くたびに時計を読まずに決める)。 */
export function useSettings() {
  const [view, setView] = useState(null)
  const [loadedAt, setLoadedAt] = useState(0)
  const [error, setError] = useState(false)
  const controller = useRef(null)

  const reload = useCallback(async () => {
    controller.current?.abort()
    controller.current = new AbortController()
    try {
      const fresh = await fetchSettings(controller.current.signal)
      setView(fresh)
      setLoadedAt(Date.now() / 1000)
      setError(false)
    } catch (e) {
      if (e.name !== 'AbortError') setError(true)
    }
  }, [])

  useEffect(() => {
    reload()
    return () => controller.current?.abort()
  }, [reload])

  /** 差分を書く。 → { ok, reasons }。 通れば画面の値を新しい値にする。 */
  const save = useCallback(async (patch) => {
    const result = await updateSettings(patch)
    if (result.ok) {
      setView(result.view)
      setLoadedAt(Date.now() / 1000)
    }
    return result
  }, [])

  /** その口座の止まったタブを続ける。 → continueAccount の答え。 続けたら読み直す。 */
  const continueTabs = useCallback(async (account) => {
    const result = await continueAccount(account)
    await reload()
    return result
  }, [reload])

  return { view, loadedAt, error, save, continueTabs, reload }
}
