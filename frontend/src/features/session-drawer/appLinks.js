// app の中で、 app を開いた URL (= `claudepwa://open?ses=<sid>`) のタブを開く。
//
// URL を出すのはホーム画面のウィジェット (= shell/ios/App/Widgets/TabsWidget.swift)、 app 側の受け手は
// shell/ios/App/App/AppLinkPlugin.swift。 ブラウザの PWA では何もしない。

function capacitor() {
  return typeof window !== 'undefined' ? window.Capacitor : null
}

// app の中で、 app を開いた URL のタブを受ける (= AppLinkPlugin の openSession)。 受けを外す関数を返す。
export function listenAppLinks(onOpen) {
  const cap = capacitor()
  if (!cap?.isNativePlatform?.() || !cap.isPluginAvailable?.('AppLink')) return () => {}
  const handle = cap.Plugins.AppLink.addListener('openSession', ({ sid } = {}) => {
    if (sid) onOpen(sid)
  })
  return () => { Promise.resolve(handle).then((h) => h?.remove?.()).catch(() => {}) }
}
