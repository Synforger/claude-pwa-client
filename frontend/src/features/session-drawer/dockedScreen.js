// タブの一覧を左に置いたままにできる画面 (= PC の広い画面) かどうかを matchMedia で読む。
// useDockedDrawer (= 画面の変化を追う hook) と dockedDrawerOpen (= 起動の復元) が呼ぶ。

// 幅が足りて、 マウスが在る画面。 iPad やスマホは重ねる形のまま (= hover と pointer で外す)。
export const DOCKED_SCREEN_QUERY = '(min-width: 1024px) and (hover: hover) and (pointer: fine)'

function mediaQueryList() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null
  return window.matchMedia(DOCKED_SCREEN_QUERY)
}

export function isDockedScreen() {
  return mediaQueryList()?.matches === true
}

// 画面が広くなる・狭くなる時に listener を呼ぶ。 返す関数で外す。
export function subscribeDockedScreen(listener) {
  const list = mediaQueryList()
  if (!list) return () => {}
  list.addEventListener('change', listener)
  return () => list.removeEventListener('change', listener)
}
