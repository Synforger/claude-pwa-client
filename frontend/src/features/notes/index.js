// features/notes 配線 entry。
//
// 📋 から開く、 タブごとのメモ (= NoteModal)。 OverlayHost が `ui.overlays.notes` で開く。
// component は static import しない (= lazy chunk を保つ。 contract test が grep gate)。

import { register as registerOverlay } from '../../registry/overlayRegistry.js'

registerOverlay('notes', {
  dispatch: () => null,
  Component: () => import('./NoteModal.jsx'),
})
