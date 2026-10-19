// path をタップした時の開き先 (= チャット・メモ・ファイルの木・お気に入りの全部の入口で同じ)。
// folder は木、 HTML はブラウザの新しいタブ (= スクリプトが動く形。 backend の /file/open が、 隣の画像ごと
// sandbox を掛けて配る)、 それ以外はプレビュー。 iPhone の app では、 新しいタブは既定のブラウザで開く。
import { setOverlay } from '../../state/ui.js'
import { apiUrl } from '../../utils/api.js'

const HTML_RE = /\.html?$/i

// onLeave = 木かプレビューへ移る直前に呼ぶ (= メモのように、 同じ場所に重なる物を畳む)。 ブラウザで開く時は呼ばない。
export function openPath(path, { onLeave } = {}) {
  if (HTML_RE.test(path)) {
    window.open(apiUrl(`/file/open?path=${encodeURIComponent(path)}`), '_blank', 'noreferrer')
    return
  }
  onLeave?.()
  if (path.endsWith('/')) setOverlay('treeOpen', path)
  else setOverlay('previewPath', path)
}
