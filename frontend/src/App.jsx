// App = mount entry のみ。 配置 / hook 連鎖 / features 配線は layout/Layout.jsx に集約
// (= W2 Phase F-6、 2026-06-29)。 旧 layout/AppShell.jsx は本 phase で物理削除、 Layout.jsx が
// 全責務を引き継ぐ。 設計書 § 3 v2 ツリー「App.jsx 薄い entry + layout/Layout.jsx 全体配置」 着地、
// ADR-010 hexagonal 整合、 完了判定 1 (= App.jsx に hook 呼出ゼロ) + 完了判定 2 (= 配置単一所有) 達成。

import Layout from './layout/Layout.jsx'

export default function App() {
  return <Layout />
}
