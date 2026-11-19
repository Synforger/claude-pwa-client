// features/tickets 配線 entry。
//
// 頼みの票の画面。 📌 (= 上の帯) から開く一覧 (`tickets`) と、 一覧・チャットの 1 行・通知から開く票の画面 (`ticket`、 値は票の id)。
// OverlayHost が `ui.overlays.tickets` / `ui.overlays.ticket` で開く。 component は static import しない
// (= lazy chunk を保つ。 contract test が grep gate)。

import { register as registerOverlay } from '../../core/overlayRegistry.js'

registerOverlay('tickets', {
  dispatch: () => null,
  Component: () => import('./TicketDrawer.jsx'),
})

registerOverlay('ticket', {
  dispatch: () => null,
  Component: () => import('./TicketView.jsx'),
})
