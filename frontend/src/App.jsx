// App = mount entry のみ。 features の hook 連鎖 + UI 配置は layout/AppShell.jsx に集約。
// 設計書 § 3 v2 ツリー: App.jsx (薄い entry) + layout/Layout.jsx (全体配置)、 ADR-010 hexagonal
// 整合。 完了判定 2 (= App.jsx に個別 hook wiring 残ってない) を満たす。

import AppShell from './layout/AppShell.jsx'

export default function App() {
  return <AppShell />
}
