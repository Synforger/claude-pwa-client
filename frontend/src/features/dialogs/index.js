// features/dialogs 配線 entry (= W2 Phase F-4、 2026-06-29)。
//
// shared/ConfirmDialog.jsx の thin wrapper を OverlayHost 経由で render するための registerOverlay
// hub。 各 dialog (= ConfirmDeleteDialog 等) は内部で state/ui.js を subscribe して props 自己解決
// (= ADR-010)、 ui.overlays.<name> が truthy になった瞬間に OverlayHost が React.lazy + Suspense +
// LazyBoundary で render する。
//
// 注: 本 phase で wrapper 化したのは confirmDelete のみ。 confirmEnd / confirmStop は ChatPanel.jsx
// が所有する `useChatStream` の戻り値 (= endSession / stopMessage 関数) に依存しており、 ChatPanel.jsx
// が本 phase のスコープ外 (= READ-only) のため移送見送り。 別 phase で useChatStream を module-level
// export 化 or sessions store に dispatch 化してから再着手する (= 親 plan の Phase F-4 残課題)。
//
// 注: ConfirmDeleteDialog.jsx を static import すると vite が dynamic import を相殺し
// INEFFECTIVE_DYNAMIC_IMPORT 警告 → chunk 分離崩壊するため、 Component spec の `() => import(...)`
// 形式のみで参照する (= features/__contracts__/no-lazy-component-static-import.test.js が grep gate)。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'

const noopDispatch = () => null
registerOverlay('confirmDelete', {
  Component: () => import('./ConfirmDeleteDialog.jsx'),
  dispatch: noopDispatch,
})
