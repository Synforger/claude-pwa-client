// session 削除確認 dialog の自己完結 wrapper (= W2 Phase F-4、 2026-06-29)。 旧 AppShell.jsx の
// `<ConfirmDialog open={!!ui.overlays.confirmDelete} ... />` + `handleDeleteSession` を物理移送、
// ロジック改変ゼロ。
//
// `ui.overlays.confirmDelete` は string sid を payload で持つ (= null = closed、 sid = open with
// target session)。 OverlayHost が truthy check で本 component を render し、 内部で
// useSyncExternalStore + setOverlay 直呼出で props 自己解決する (= ADR-010)。
//
// shared/ConfirmDialog.jsx 自体は touch せず、 wrapper として呼び出す。

import { useSyncExternalStore, useCallback } from 'react'
import {
  subscribe as subscribeUi,
  getSnapshot as getUiSnapshot,
  setOverlay,
} from '../../state/ui.js'
import { removeSession } from '../session-drawer/useSessions.js'
import ConfirmDialog from '../../shared/ConfirmDialog.jsx'

export default function ConfirmDeleteDialog() {
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  const sid = ui.overlays.confirmDelete

  const handleCancel = useCallback(() => setOverlay('confirmDelete', null), [])
  const handleConfirm = useCallback(async () => {
    const target = ui.overlays.confirmDelete
    if (!target) return
    setOverlay('confirmDelete', null)
    await removeSession(target)
    // F-1 注: 旧 AppShell では setMessages で sid を dict から落として gcImages を即時呼出して
    // いたが、 messages / setMessages は ChatPanel が所有するようになったため、 ここでは追加 cleanup
    // を行わない。 useChatStorage.runMsgSave が sessions 更新を契機に v2 localStorage key を自動
    // remove するので永続化側は同等。 orphan IDB 画像は ChatPanel 内の起動時 1 回 GC + 次回再起動時
    // の GC で回収される (= 即時性は失うが整合性は保たれる、 review 確認事項参照)。
  }, [ui.overlays.confirmDelete])

  return (
    <ConfirmDialog
      open={!!sid}
      text={
        <>
          この会話を削除しますか？
          <br />
          <span className="dim">会話履歴も削除されます。 元に戻せません。</span>
        </>
      }
      onCancel={handleCancel}
      onConfirm={handleConfirm}
    />
  )
}
