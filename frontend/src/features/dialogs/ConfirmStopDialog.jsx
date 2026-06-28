// 推論停止確認 dialog の自己完結 wrapper (= W2 Phase F-4 残、 2026-06-29)。 旧 ChatPanel.jsx の
// `<ConfirmDialog open={ui.overlays.confirmStop} ... />` + onConfirm inline を物理移送、
// ロジック改変ゼロ。
//
// `ui.overlays.confirmStop` は boolean (= true で open)。 OverlayHost が truthy check で本 component
// を render し、 内部で useSyncExternalStore + setOverlay 直呼出 + features/chat/useChatStream
// の module-level `stopMessage` 経由で props 自己解決する (= ADR-010)。
//
// shared/ConfirmDialog.jsx 自体は touch せず、 wrapper として呼び出す。

import { useSyncExternalStore, useCallback } from 'react'
import {
  subscribe as subscribeUi,
  getSnapshot as getUiSnapshot,
  setOverlay,
} from '../../state/ui.js'
import { stopMessage } from '../chat/useChatStream.js'
import ConfirmDialog from '../../shared/ConfirmDialog.jsx'

export default function ConfirmStopDialog() {
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  const open = !!ui.overlays.confirmStop

  const handleCancel = useCallback(() => setOverlay('confirmStop', false), [])
  const handleConfirm = useCallback(() => {
    setOverlay('confirmStop', false)
    stopMessage()
  }, [])

  return (
    <ConfirmDialog
      open={open}
      text="推論を停止しますか?"
      onCancel={handleCancel}
      onConfirm={handleConfirm}
    />
  )
}
