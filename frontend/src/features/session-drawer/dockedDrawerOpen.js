// 左に置いたままのタブの一覧 (= docked) の開け閉めを、 機械ごとに localStorage へ覚える。
// 開け閉めの真値は今までと同じ ui.overlays.drawer で、 ここはその値の書き換え口と、 覚えた値を戻す口だけを持つ。
// 保存は操作 (= ☰・✕) の口 setDrawerOpen だけが行うので、 画面の幅の変化や起動で値を書き換えることは無い。

import { LS_DRAWER_DOCKED } from '../../_common/constants.js'
import { lsGet, lsSet } from '../../_common/storage.js'
import { setOverlay } from '../../state/ui.js'
import { isDockedScreen } from './dockedScreen.js'

// 覚えた値。 無い (= 初めて) と壊れた値は開いた状態 (= PC で毎回 ☰ を押さなくてよい)。
export function loadDockedOpen() {
  return lsGet(LS_DRAWER_DOCKED, true) !== false
}

// 操作で一覧を開け閉めする。 docked の時だけ覚える (= 重ねる形の開け閉めは覚えない)。
export function setDrawerOpen(open, { docked }) {
  setOverlay('drawer', open)
  if (docked) lsSet(LS_DRAWER_DOCKED, open)
}

// 画面の広さに合わせて、 今の開け閉めを決める。 広い画面は覚えた値、 狭い画面は閉じる (= 覚えた値は触らない)。
export function restoreDrawerOpen() {
  setOverlay('drawer', isDockedScreen() ? loadDockedOpen() : false)
}
