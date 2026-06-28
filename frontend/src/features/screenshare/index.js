// features/screenshare 配線 entry。
//
// W2 Phase E1 (= overlayRegistry Component spec 化): MoonlightFrame を OverlayHost 経由で render
// するため、 `desktopOpen` を overlayRegistry に追加し `Component` lazy spec を持たせる。
// featureRegistry の `screenshare` capability signal は別 layer (= 横断 feature 有効判定) として
// 残置。 OverlayHost が describe('desktopOpen') で取得 → React.lazy で wrap → `ui.overlays.desktopOpen`
// truthy で開く経路に組み込む。 旧 AppShell.jsx 内 `desktopOpen && moonlightAvailable && <MoonlightFrame />`
// は削除済、 moonlightAvailable 判定は MoonlightFrame.jsx 内部に移送 (= 利用不可なら early return null)。

import { register as registerFeature } from '../../registry/featureRegistry.js'
import { register as registerOverlay } from '../../registry/overlayRegistry.js'

const noopDispatch = () => null
registerFeature('screenshare', { dispatch: noopDispatch })
registerOverlay('desktopOpen', {
  Component: () => import('./MoonlightFrame.jsx'),
  dispatch: noopDispatch,
})
