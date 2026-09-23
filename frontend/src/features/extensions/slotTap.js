// 🧩 をタップした時にどの拡張を開くか。 開いている拡張があれば畳み、 無ければ最後に開いた拡張を開く
// (= 最後に開いた拡張が届かなくなっていれば、 一覧の先頭)。 最後に開いた拡張は端末ごとに保存する。
import { lsGet, lsSet } from '../../utils/storage.js'

// iOS の標準的な長押しと同じ長さ。 これより長く押すと一覧を出す。
export const SLOT_LONG_PRESS_MS = 500
const LS_KEY = 'cpc.extensions.lastId'

// 戻り値: 次の `ui.overlays.extensionOpen` の値 (= 開く id か、 畳むなら null)。
export function nextOpenOnTap(extensions, openId, lastId) {
  if (!Array.isArray(extensions) || extensions.length === 0) return null
  if (openId && extensions.some((ext) => ext.id === openId)) return null
  const last = extensions.find((ext) => ext.id === lastId)
  return (last || extensions[0]).id
}

export function loadLastId() {
  const id = lsGet(LS_KEY, null)
  return typeof id === 'string' ? id : null
}

export function saveLastId(id) {
  if (typeof id === 'string') lsSet(LS_KEY, id)
}
