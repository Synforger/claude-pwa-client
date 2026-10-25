// 外の物 (= HTML のページ・web のリンク・外の画像) を、 client の外のブラウザで開く。 呼び手は path の開き先
// (= features/file-preview/openPath.js) とチャットのリンク (= features/chat/MessageRenderer.jsx)。
//
// Mac・PC のブラウザは新しいタブ。 iPhone の app は新しい窓を PageSheetPlugin が受けて OS の既定のブラウザへ渡す。
// iPhone / iPad のホーム画面の PWA だけは、 新しいタブで開くと PWA の中の閲覧の画面になり (= client の中のまま)、
// 既定のブラウザへ渡す web の口が無い。 iOS は `x-safari-https://` の形の URL を Safari へ渡すので、 そこだけ
// この形で OS に渡す (= 既定のブラウザが Safari 以外でも Safari で開く)。 PWA の画面は置き換わらずに残る。

// Safari へ渡す形の URL (= http(s) 以外は null)
export function safariUrl(url) {
  const match = /^(https?):\/\//i.exec(url)
  return match ? `x-safari-${match[1].toLowerCase()}://${url.slice(match[0].length)}` : null
}

// iPhone / iPad のホーム画面から開いた PWA か (= `navigator.standalone` は iOS の WebKit だけが持ち、 ホーム画面から
// 開いた時だけ true。 iPhone の app の WKWebView は false)
export function isHomeScreenWebApp(win = window) {
  if (win.Capacitor?.isNativePlatform?.()) return false
  return win.navigator?.standalone === true
}

export function openInBrowser(url, win = window) {
  const absolute = new URL(url, win.location.href).href
  const safari = isHomeScreenWebApp(win) ? safariUrl(absolute) : null
  if (safari) {
    win.location.href = safari
    return
  }
  win.open(absolute, '_blank', 'noreferrer')
}
