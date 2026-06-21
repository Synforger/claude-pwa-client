// タブごとの表示モード (= 'chat' | 'terminal') を localStorage 永続化込みで管理する hook
// (= F-03)。 旧 App.jsx 直書きでは `viewModes` state + lsSet effect + activeViewMode 派生
// + flippedViewMode 派生 + toggle 直書きで 4 か所散らばっていた。 1 つに集約する。
//
// 「terminal タブ」 = デバッグ用に生 xterm を見たい tab だけ terminal、 別 tab は chat。
// localStorage `cpc_view_modes` で「タブ ID → mode」 を保存し、 リロード後も復元する。
import { useState, useEffect, useCallback } from 'react'
import { lsGet, lsSet } from '../utils/storage.js'

const LS_KEY = 'cpc_view_modes'

export function useViewMode(activeSid) {
  const [viewModes, setViewModes] = useState(() => lsGet(LS_KEY) || {})
  useEffect(() => { lsSet(LS_KEY, viewModes) }, [viewModes])

  const activeViewMode = activeSid ? (viewModes[activeSid] || 'chat') : 'chat'
  // toggle ヘルパは「現在 mode → 反転 mode」 を計算する純粋関数として残し、
  // 実際の setViewModes 呼出は呼び出し側で行う (= topbar の 💬 戻るボタンと
  // ⋯ メニュー側を「set 直書き」 経路に統一して、 useCallback closure 経由で
  // 動かない疑惑を消す = 旧 App.jsx 直書きの設計コメントを継承)。
  const flippedViewMode = activeViewMode === 'terminal' ? 'chat' : 'terminal'

  // active sid の mode を直接 set するヘルパ。 sid 無し時は no-op。
  const setActiveViewMode = useCallback((mode) => {
    if (!activeSid) return
    setViewModes(prev => ({ ...prev, [activeSid]: mode }))
  }, [activeSid])

  return { viewModes, setViewModes, activeViewMode, flippedViewMode, setActiveViewMode }
}
