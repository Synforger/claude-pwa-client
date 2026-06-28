// features/file-tree 配線 entry。
//
// W2 Phase E1 (= overlayRegistry Component spec 化): FileTreePanel / FavoritesQuickPicker を
// OverlayHost 経由で render するため、 `Component` lazy spec を 2 件 register に追加。 OverlayHost が
// describe('treeOpen') / describe('favs') で取得 → React.lazy で wrap → `ui.overlays.treeOpen` /
// `ui.overlays.favs` truthy で開く経路に組み込む。 旧 AppShell.jsx 内 `lazy(...)` 2 件は AppShell
// 側から削除済 (= 中央非依存達成)。
//
// 注: ここで component を static import すると vite が dynamic import を相殺し
// INEFFECTIVE_DYNAMIC_IMPORT 警告 → chunk 分離崩壊するため、 Component spec の `() => import(...)`
// 形式のみで参照する。 contract test (= no-lazy-component-static-import.test.js) が grep gate。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'

import './favorites.js'

const noopDispatch = () => null
registerOverlay('treeOpen', {
  Component: () => import('./FileTreePanel.jsx'),
  dispatch: noopDispatch,
})
registerOverlay('favs', {
  Component: () => import('./FavoritesQuickPicker.jsx'),
  dispatch: noopDispatch,
})
