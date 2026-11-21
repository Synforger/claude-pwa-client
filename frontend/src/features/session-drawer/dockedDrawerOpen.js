// Remembers per machine, in localStorage, whether the tab list kept on the left (docked) is open.
// The truth of open / shut is still ui.overlays.drawer; this file only writes it and puts the remembered value back.
// Only setDrawerOpen, the entry of an operation (☰, ✕), saves, so a change of window size or a start never rewrites it.

import { LS_DRAWER_DOCKED } from '../../_common/constants.js'
import { lsGet, lsSet } from '../../_common/storage.js'
import { setOverlay } from '../../state/ui.js'
import { isDockedScreen } from './dockedScreen.js'

// The remembered value. Nothing remembered, or a broken value, means open, so a PC need not press ☰ each time.
export function loadDockedOpen() {
  return lsGet(LS_DRAWER_DOCKED, true) !== false
}

// Opens or shuts the list by an operation. Only the docked form is remembered, not the overlay form's.
export function setDrawerOpen(open, { docked }) {
  setOverlay('drawer', open)
  if (docked) lsSet(LS_DRAWER_DOCKED, open)
}

// Decides open / shut for the screen's width: as remembered when wide, shut when narrow (what is remembered is not touched).
export function restoreDrawerOpen() {
  setOverlay('drawer', isDockedScreen() ? loadDockedOpen() : false)
}
