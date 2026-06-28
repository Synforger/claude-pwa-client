// 画面共有 (moonlight-web-stream) が利用可能かをマウント時に検出。
// useAppEffects.js から物理移送 (= W2 Phase C、 screenshare 専属)。
import { useEffect, useState } from 'react'
import { apiFetch } from '../../utils/api.js'


// --- 画面共有 (= moonlight-web-stream) が利用可能かをマウント時に検出 ---
// Path B (= Sunshine + moonlight-web-stream セットアップ済) のユーザだけ
// 🖥 ボタンを表示する。 backend に対して `/moonlight/` への HEAD を 1 回投げて
// 2xx なら有効、 404 / network error なら無効と判定。 結果をマウント中保持。
export function useMoonlightAvailable() {
  const [available, setAvailable] = useState(false)
  useEffect(() => {
    // e2e seam: scenarios that need the screenshare toggle visible without a
    // real Sunshine + moonlight reverse proxy can flip a localStorage flag.
    try {
      if (typeof window !== 'undefined' && localStorage.getItem('cpc_e2e_moonlight') === '1') {
        setAvailable(true)
        return undefined
      }
    } catch {
      // localStorage may throw under strict privacy modes; treat as unset.
    }
    let cancelled = false
    ;(async () => {
      try {
        const res = await apiFetch(`/moonlight/`, { method: 'HEAD', credentials: 'same-origin' })
        if (!cancelled) setAvailable(res.ok)
      } catch {
        if (!cancelled) setAvailable(false)
      }
    })()
    return () => { cancelled = true }
  }, [])
  return available
}
