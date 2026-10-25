// path をタップした時の開き先 (= チャット・メモ・ファイルの木・お気に入りの全部の入口で同じ)。
// HTML (= .html / .htm) だけが client の外のブラウザで開く (= スクリプトが動く形。 backend の /file/open が、 隣の画像ごと
// sandbox を掛けて配る。 設定の page_origin の folder の物は、 sandbox の無い別の port へ回す)。 どのブラウザへ渡すかは
// _common/externalBrowser.js (= Mac・PC は新しいタブ、 iPhone の app とホーム画面の PWA は OS へ渡す)。
// folder は木、 それ以外 (= Markdown・画像・資料の pdf・Office・tif) は client の中のプレビュー。 資料はプレビューの
// 枠の中で、 backend が頁の画像にして返した頁を見せる。
import { setOverlay } from '../../state/ui.js'
import { apiUrl } from '../../_common/api.js'
import { openInBrowser } from '../../_common/externalBrowser.js'

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
