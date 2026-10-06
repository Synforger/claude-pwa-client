// 拡張 (= 別 repo のアプリを `/ext/<id>/` で iframe に嵌める口) の一覧。
//
// backend の `GET /extensions` が config の宣言を返し、 各 path に HEAD を 1 回投げて 2xx の物だけを
// 残す (= 画面共有の `useMoonlightAvailable` と同じ判定)。 宣言していても Tailscale Serve に載って
// いない拡張はボタンを出さない。 🧩 の一覧 (= ExtensionMenu) と枠 (= ExtensionHost) が同じ結果を読むので、 取得は
// module 内で 1 回だけ行う (= PWA の再読込で取り直す)。
import { useEffect, useState, useSyncExternalStore } from 'react'
import { apiFetch } from '../../utils/api.js'
import { subscribe as subscribeUi, getSnapshot as getUiSnapshot } from '../../state/ui.js'

// 宣言の一覧から、 head(path) が true を返した物だけを宣言順で残す。 1 件の失敗は他を巻き込まない。
export async function resolveReachable(declared, head) {
  if (!Array.isArray(declared)) return []
  const reachable = await Promise.all(declared.map(async (ext) => {
    try {
      return await head(ext.path)
    } catch {
      return false
    }
  }))
  return declared.filter((_, i) => reachable[i])
}

async function headOk(path) {
  const res = await apiFetch(path, { method: 'HEAD', credentials: 'same-origin' })
  return res.ok
}

async function loadExtensions() {
  try {
    const res = await apiFetch('/extensions')
    if (!res.ok) return []
    return await resolveReachable(await res.json(), headOk)
  } catch {
    return []
  }
}

let pending = null

export function useExtensions() {
  const [extensions, setExtensions] = useState([])
  useEffect(() => {
    let cancelled = false
    if (!pending) pending = loadExtensions()
    pending.then((list) => { if (!cancelled) setExtensions(list) })
    return () => { cancelled = true }
  }, [])
  return extensions
}

// 拡張の開き方は宣言の `view` が持つ: 'band' = チャットの上の帯、 'page' = 入力欄の上を全部使う頁。
// 頁が開いている間、 メッセージの一覧と端末はその場所を譲る (= 入力欄は残る)。 枠 (= ExtensionHost) と
// それらが同じ判定を読むように、 判定はここ 1 か所に置く。
export function isPageOpen(extensions, openId) {
  return extensions.some((ext) => ext.id === openId && ext.view === 'page')
}

export function usePageExtensionOpen() {
  const extensions = useExtensions()
  const openId = useSyncExternalStore(subscribeUi, () => getUiSnapshot().overlays.extensionOpen)
  return isPageOpen(extensions, openId)
}
