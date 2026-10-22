// path をタップした時の開き先 (= チャット・メモ・ファイルの木・お気に入りの全部の入口で同じ)。
// HTML (= .html / .htm) だけが OS の既定のブラウザで開く (= スクリプトが動く形。 backend の /file/open が、 隣の画像ごと
// sandbox を掛けて配る。 設定の page_origin の folder の物は、 sandbox の無い別の port へ回す)。 Mac・PC のブラウザは
// 新しいタブ、 iPhone の app は新しい窓を PageSheetPlugin が受けて既定のブラウザへ渡す。
// folder は木、 それ以外 (= Markdown・画像・資料の pdf・Office・tif) は client の中のプレビュー。 資料はプレビューの
// 枠の中で、 backend が頁の画像にして返した頁を見せる。
// iPhone / iPad のホーム画面の PWA は、 HTML もプレビューの枠で開く (= 枠の中の iframe)。 既定のブラウザへ渡す口が
// 公式の資料に無く、 新しいタブのはずの /file/view は PWA の画面ごと置き換わって、 会話へ戻れなくなる。
import { setOverlay } from '../../state/ui.js'
import { apiUrl } from '../../_common/api.js'
import { isStandalone, isMobileSafari } from '../push-notify/push.js'

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

// 新しいタブで開くと戻れない形 (= iOS のホーム画面の PWA。 iPhone の app は既定のブラウザへ渡すので会話の画面が残る)
function opensInPlace() {
  if (typeof window === 'undefined') return false
  if (window.Capacitor?.isNativePlatform?.()) return false
  return isStandalone() && isMobileSafari()
}

// onLeave = 木かプレビューへ移る直前に呼ぶ (= メモのように、 同じ場所に重なる物を畳む)。 既定のブラウザで開く時は呼ばない。
export function openPath(path, { onLeave } = {}) {
  if (isHtmlPath(path) && !opensInPlace()) {
    window.open(apiUrl(`/file/open?path=${encodeURIComponent(path)}`), '_blank', 'noreferrer')
    return
  }
  onLeave?.()
  if (path.endsWith('/')) setOverlay('treeOpen', path)
  else setOverlay('previewPath', path)
}
