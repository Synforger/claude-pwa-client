// Whether the screen now can keep the tab list on the left (follows the window when it changes size).
// Read by Layout (pushes the body), SessionDrawer (no curtain, stays after a choice) and Topbar (what ☰ does).

import { useEffect, useSyncExternalStore } from 'react'
import { isDockedScreen, subscribeDockedScreen } from './dockedScreen.js'
import { restoreDrawerOpen } from './dockedDrawerOpen.js'

export function useDockedDrawer() {
  return useSyncExternalStore(subscribeDockedScreen, isDockedScreen)
}

// Decides open / shut again when the screen turns wide or narrow (shut when narrow, as remembered when wide).
// The start is already done by AppEffects at module load, so on the first run this only sets the same value again.
export function useDockedDrawerRestore() {
  const docked = useDockedDrawer()
  useEffect(() => { restoreDrawerOpen() }, [docked])
}
