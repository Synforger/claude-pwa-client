// app の中で、 app を開いた URL (= `claudepwa://open?ses=<sid>`) のタブを開く。 `&call=1` が付いていれば
// (= Siri の「通話」)、 そのタブで声とマイクの会話も始める。 `claudepwa://open?ticket=<id>` なら、 その票の画面を開く
// (= 票の通知。 AppLinkPlugin の openTicket)。
//
// URL を出すのはホーム画面のウィジェット (= shell/ios/App/Widgets/TabsWidget.swift)、 app 側の受け手は
// shell/ios/App/App/AppLinkPlugin.swift。 ブラウザの PWA では何もしない。

function capacitor() {
  return typeof window !== 'undefined' ? window.Capacitor : null
}

// app の中で、 app を開いた URL のタブを受ける (= AppLinkPlugin の openSession)。 onOpen(sid, { call }) を呼び、
// 受けを外す関数を返す。 `onOpenTicket(ticket)` は票の URL を受けた時に呼ぶ。
export function listenAppLinks(onOpen, onOpenTicket = () => {}) {
  const cap = capacitor()
  if (!cap?.isNativePlatform?.() || !cap.isPluginAvailable?.('AppLink')) return () => {}
  const handles = [
    cap.Plugins.AppLink.addListener('openSession', ({ sid, call } = {}) => {
      if (sid) onOpen(sid, { call: call === true })
    }),
    cap.Plugins.AppLink.addListener('openTicket', ({ ticket } = {}) => {
      if (ticket) onOpenTicket(ticket)
    }),
  ]
  return () => { for (const handle of handles) Promise.resolve(handle).then((h) => h?.remove?.()).catch(() => {}) }
}
