// features/screenshare 配線 entry。
//
// MoonlightFrame.jsx は AppShell.jsx で lazy(() => import(...)) される (= 画面共有を開いた瞬間に chunk fetch)。
// 配線 entry での static import は chunk 分離を壊すため、 entry は registry signal のみ。

import { register as registerFeature } from '../../registry/featureRegistry.js'

registerFeature('screenshare', { dispatch: () => null })
