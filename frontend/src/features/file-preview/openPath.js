// path をタップした時の開き先 (= チャット・メモ・ファイルの木・お気に入りの全部の入口で同じ)。
// folder は木、 HTML はブラウザの新しいタブ (= スクリプトが動く形。 backend の /file/open が、 隣の画像ごと
// sandbox を掛けて配る。 設定の page_origin の folder の物は、 sandbox の無い別の port へ回す)、 それ以外はプレビュー。 iPhone の app では、 新しいタブは app の中の閲覧の画面で開く。
// iPhone / iPad のホーム画面の PWA は、 HTML もプレビューの枠で開く (= 枠の中の iframe)。 PWA には戻る口が無く、
// 新しいタブのはずの /file/view が PWA の画面ごと置き換わって、 会話へ戻れなくなる。
import { setOverlay } from '../../state/ui.js'
import { apiUrl } from '../../utils/api.js'
import { isStandalone, isMobileSafari } from '../push-notify/push.js'

const HTML_RE = /\.html?$/i

export function isHtmlPath(path) {
  return HTML_RE.test(path)
}

// 新しいタブで開くと戻れない形 (= iOS のホーム画面の PWA。 iPhone の app は閲覧の画面が戻る口を持つ)
function opensInPlace() {
  if (typeof window === 'undefined') return false
  if (window.Capacitor?.isNativePlatform?.()) return false
  return isStandalone() && isMobileSafari()
}

// onLeave = 木かプレビューへ移る直前に呼ぶ (= メモのように、 同じ場所に重なる物を畳む)。 ブラウザで開く時は呼ばない。
export function openPath(path, { onLeave } = {}) {
  if (isHtmlPath(path) && !opensInPlace()) {
    window.open(apiUrl(`/file/open?path=${encodeURIComponent(path)}`), '_blank', 'noreferrer')
    return
  }
  onLeave?.()
  if (path.endsWith('/')) setOverlay('treeOpen', path)
  else setOverlay('previewPath', path)
}
