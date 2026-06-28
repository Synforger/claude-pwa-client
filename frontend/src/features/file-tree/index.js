// features/file-tree 配線 entry。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'

import './FileTreePanel.jsx'
import './FavoritesQuickPicker.jsx'
import './favorites.js'

const noopDispatch = () => null
registerOverlay('treeOpen', { dispatch: noopDispatch })
registerOverlay('favs',     { dispatch: noopDispatch })
