// 今の画面がタブの一覧を左に置いたままにできる画面か (= 窓の幅が変われば追う)。
// Layout (寄せる)・SessionDrawer (幕を出さない・選んでも閉じない)・Topbar (☰ の動き) が読む。

import { useEffect, useSyncExternalStore } from 'react'
import { isDockedScreen, subscribeDockedScreen } from './dockedScreen.js'
import { restoreDrawerOpen } from './dockedDrawerOpen.js'

export function useDockedDrawer() {
  return useSyncExternalStore(subscribeDockedScreen, isDockedScreen)
}

// 画面の広さが変わった時に開け閉めを決め直す (= 狭くなれば閉じ、 広くなれば覚えた値で開け閉めする)。
// 起動の 1 回目は AppEffects の module load で済んでいるので、 ここは同じ値を入れ直すだけで動きは無い。
export function useDockedDrawerRestore() {
  const docked = useDockedDrawer()
  useEffect(() => { restoreDrawerOpen() }, [docked])
}
