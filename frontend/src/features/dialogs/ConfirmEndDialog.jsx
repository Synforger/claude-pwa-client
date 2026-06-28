// session 終了確認 dialog の自己完結 wrapper (= W2 Phase F-4 残、 2026-06-29)。 旧 ChatPanel.jsx の
// `<ConfirmDialog open={ui.overlays.confirmEnd} ... />` + `handleEndSession` を物理移送、
// ロジック改変ゼロ。
//
// `ui.overlays.confirmEnd` は boolean (= true で open)。 OverlayHost が truthy check で本 component
// を render し、 内部で useSyncExternalStore + setOverlay 直呼出 + features/chat/useChatStream
// の module-level `endSession` 経由で props 自己解決する (= ADR-010)。
//
// shared/ConfirmDialog.jsx 自体は touch せず、 wrapper として呼び出す。

import { useSyncExternalStore, useCallback } from 'react'
import {
  subscribe as subscribeUi,
  getSnapshot as getUiSnapshot,
  setOverlay,
} from '../../state/ui.js'
import { endSession } from '../chat/useChatStream.js'
import ConfirmDialog from '../../shared/ConfirmDialog.jsx'

export default function ConfirmEndDialog() {
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  const open = !!ui.overlays.confirmEnd

  const handleCancel = useCallback(() => setOverlay('confirmEnd', false), [])
  const handleConfirm = useCallback(() => {
    // 旧 ChatPanel.handleEndSession 同等: menu close + confirmEnd close + endSession 発火。
    setOverlay('menu', false)
    setOverlay('confirmEnd', false)
    endSession()
  }, [])

  return (
    <ConfirmDialog
      open={open}
      text="このセッションを終了しますか?"
      onCancel={handleCancel}
      onConfirm={handleConfirm}
    />
  )
}
