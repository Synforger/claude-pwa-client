// 設定の画面の 1 つの card の「入力 → 差分 → 保存」。 card は入力 (draft) を持ち、 差分を作る関数を渡す。
import { useCallback, useState } from 'react'

/** → { saving, reasons, saved, run(patch) }。 run は保存を 1 回行い、 backend が断った理由を reasons に残す。 */
export function useCardSave(save) {
  const [saving, setSaving] = useState(false)
  const [reasons, setReasons] = useState([])
  const [saved, setSaved] = useState(false)
  const run = useCallback(async (patch) => {
    setSaving(true)
    setReasons([])
    setSaved(false)
    try {
      const result = await save(patch)
      if (result.ok) setSaved(true)
      else setReasons(result.reasons.length ? result.reasons : [`HTTP ${result.status}`])
    } catch (e) {
      setReasons([String(e?.message || e)])
    } finally {
      setSaving(false)
    }
  }, [save])
  return { saving, reasons, saved, run }
}
