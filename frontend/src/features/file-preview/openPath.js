// path をタップした時の開き先 (= チャット・メモ・ファイルの木・お気に入りの全部の入口で同じ)。
// HTML (= .html / .htm) だけが client の外のブラウザで開く (= スクリプトが動く形。 backend の /file/open が、 隣の画像ごと
// sandbox を掛けて配る。 設定の page_origin の folder の物は、 sandbox の無い別の port へ回す)。 どのブラウザへ渡すかは
// _common/externalBrowser.js (= Mac・PC は新しいタブ、 iPhone の app とホーム画面の PWA は OS へ渡す)。
// folder は木、 それ以外 (= Markdown・画像・資料の pdf・Office・tif) は client の中のプレビュー。 資料はプレビューの
// 枠の中で、 backend が頁の画像にして返した頁を見せる。
//
// Links written in the chat and the memo go through `openLinkedPath`: on a computer a folder opens in Finder on the
// machine the backend runs on, and everything else opens as above. An iPhone or iPad keeps the tree, since its
// operator may not be near that machine. The file tree and the favorites stay in the tree, which is where they browse.
import { setOverlay } from '../../state/ui.js'
import { apiFetch, apiUrl } from '../../_common/api.js'
import { openInBrowser } from '../../_common/externalBrowser.js'
import { isMobileSafari } from '../push-notify/push.js'

const HTML_RE = /\.html?$/i
// backend の資料の口が頁にして返す拡張子 (= `backend/documents/convert.py` の PDF / OFFICE / TIFF と同じ)
const DOCUMENT_RE = /\.(pdf|pptx|xlsx|docx|tiff?)$/i

export function isHtmlPath(path) {
  return HTML_RE.test(path)
}

// プレビューの枠が iframe の頁として見せる path (= HTML と資料。 資料は backend が頁の画像の頁にして返す)
export function isPagePath(path) {
  return HTML_RE.test(path) || DOCUMENT_RE.test(path)
}

// onLeave = 木かプレビューへ移る直前に呼ぶ (= メモのように、 同じ場所に重なる物を畳む)。 外のブラウザで開く時は呼ばない。
export function openPath(path, { onLeave } = {}) {
  if (isHtmlPath(path)) {
    openInBrowser(apiUrl(`/file/open?path=${encodeURIComponent(path)}`))
    return
  }
  onLeave?.()
  if (path.endsWith('/')) setOverlay('treeOpen', path)
  else setOverlay('previewPath', path)
}

async function revealFolder(path) {
  try {
    const response = await apiFetch('/file/reveal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    })
    return response.ok && (await response.json()).revealed === true
  } catch {
    return false
  }
}

// Only the backend knows whether a path is a folder (= agents often leave out the last `/`), so it is asked first.
// HTML is decided without waiting: a browser opens a new tab only within the tap itself.
export async function openLinkedPath(path, { onLeave } = {}) {
  if (!isHtmlPath(path) && !isMobileSafari() && await revealFolder(path)) return
  openPath(path, { onLeave })
}
