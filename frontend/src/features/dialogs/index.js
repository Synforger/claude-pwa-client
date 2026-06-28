// features/dialogs 配線 entry (= W2 Phase F-4、 2026-06-29)。
//
// shared/ConfirmDialog.jsx の thin wrapper を OverlayHost 経由で render するための registerOverlay
// hub。 各 dialog (= ConfirmDeleteDialog 等) は内部で state/ui.js を subscribe して props 自己解決
// (= ADR-010)、 ui.overlays.<name> が truthy になった瞬間に OverlayHost が React.lazy + Suspense +
// LazyBoundary で render する。
//
// 注: W2 Phase F-4 残 (= 2026-06-29) で confirmEnd / confirmStop も移送完了。 useChatStream.js
// に module-level `endSession` / `stopMessage` export を追加し (= hook mount 時に内部 closure 実装
// を wire、 unmount で nullify)、 ConfirmEndDialog / ConfirmStopDialog が直接 import する経路にした。
// ChatPanel.jsx の対応 ConfirmDialog block + handleEndSession は同 phase で退役、 hook 戻り値経由
// の参照も解消。 confirmDelete と合わせて dialogs 3 件すべて OverlayHost 経由化が完了。
//
// 注: 各 Dialog.jsx を static import すると vite が dynamic import を相殺し
// INEFFECTIVE_DYNAMIC_IMPORT 警告 → chunk 分離崩壊するため、 Component spec の `() => import(...)`
// 形式のみで参照する (= features/__contracts__/no-lazy-component-static-import.test.js が grep gate)。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'

const noopDispatch = () => null
registerOverlay('confirmDelete', {
  Component: () => import('./ConfirmDeleteDialog.jsx'),
  dispatch: noopDispatch,
})
registerOverlay('confirmEnd', {
  Component: () => import('./ConfirmEndDialog.jsx'),
  dispatch: noopDispatch,
})
registerOverlay('confirmStop', {
  Component: () => import('./ConfirmStopDialog.jsx'),
  dispatch: noopDispatch,
})
