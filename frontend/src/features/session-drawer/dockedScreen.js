// Reads with matchMedia whether the screen can keep the tab list on the left (a wide screen with a mouse).
// Called by useDockedDrawer (follows the window) and dockedDrawerOpen (the restore at start).

// Wide enough and with a mouse; hover and pointer leave out phones and tablets, which keep the overlay form.
export const DOCKED_SCREEN_QUERY = '(min-width: 1024px) and (hover: hover) and (pointer: fine)'

function mediaQueryList() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null
  return window.matchMedia(DOCKED_SCREEN_QUERY)
}

export function isDockedScreen() {
  return mediaQueryList()?.matches === true
}

// Calls the listener when the screen turns wide or narrow; the returned function removes it.
export function subscribeDockedScreen(listener) {
  const list = mediaQueryList()
  if (!list) return () => {}
  list.addEventListener('change', listener)
  return () => list.removeEventListener('change', listener)
}
