// 拡張の帯の高さ (= 画面の高さに対する %)。 帯の下端の取っ手をドラッグして変え、 端末ごとに保存する。
import { lsGet, lsSet } from '../../utils/storage.js'

// 15% より低いと拡張の中身がほぼ見えず、 70% より高いとチャットの入力欄が押し出される。
export const BAND_MIN_PCT = 15
export const BAND_MAX_PCT = 70
export const BAND_DEFAULT_PCT = 30
const LS_KEY = 'cpc.extensions.bandPct'

export function clampBandPct(pct) {
  if (typeof pct !== 'number' || !Number.isFinite(pct)) return BAND_DEFAULT_PCT
  return Math.min(BAND_MAX_PCT, Math.max(BAND_MIN_PCT, pct))
}

// ドラッグ開始時の高さ + 指の移動量 (= px) から、 新しい高さ (%) を出す。
export function pctAfterDrag(startPct, deltaY, viewportHeight) {
  if (!viewportHeight) return clampBandPct(startPct)
  return clampBandPct(startPct + (deltaY / viewportHeight) * 100)
}

export function loadBandPct() {
  return clampBandPct(lsGet(LS_KEY, BAND_DEFAULT_PCT))
}

export function saveBandPct(pct) {
  lsSet(LS_KEY, clampBandPct(pct))
}
