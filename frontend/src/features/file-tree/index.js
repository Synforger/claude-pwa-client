// features/file-tree 配線 entry。
//
// FileTreePanel.jsx / FavoritesQuickPicker.jsx は AppShell.jsx 側で lazy(() => import(...)) され、
// 「開いた瞬間に chunk fetch」 する設計 (= docs/extending.md (c) の chunk 分割方針)。 配線 entry で
// component を static import すると vite が dynamic import を相殺し INEFFECTIVE_DYNAMIC_IMPORT
// 警告を出して chunk 分離が壊れるため、 entry は registry signal と lazy 対象外の pure module load
// (= favorites.js 等) のみに絞る。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'

import './favorites.js'

const noopDispatch = () => null
registerOverlay('treeOpen', { dispatch: noopDispatch })
registerOverlay('favs',     { dispatch: noopDispatch })
