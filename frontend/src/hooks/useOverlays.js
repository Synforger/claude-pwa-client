// App.jsx に散在する overlay / modal / dialog 系 local state を 1 hook に集約する
// (= F-03)。 各 state は独立した useState のまま (= 利用箇所が touch する state だけが
// re-render を起こす React の挙動を維持、 集約による再 render 退行を出さない)。
//
// App.jsx 側は `const ov = useOverlays()` 1 行で 11 個の useState 宣言が消え、 新規
// overlay 追加時もこの hook を 1 箇所触るだけで済む。 視覚的に App.jsx 本体が
// 「UI 構築 + データ取得 + effect」 に集中できる。
//
// 入っているもの (= 単純 open/close + 値持ち overlay):
//   - drawer  : session 一覧 drawer
//   - menu    : ChatInput 内 ⋯ メニュー
//   - favs    : お気に入り Quick Picker
//   - tasks   : Task 一覧モーダル
//   - subagents (+ subagentsFocus) : サブエージェントモーダル + 開く時の focus 先
//   - previewPath  : FilePreviewModal を開く file path (null で閉)
//   - treeOpen     : FileTreePanel を開く dir path (null で閉)
//   - confirmEnd / confirmStop : ConfirmDialog (boolean)
//   - confirmDelete : 削除確認中の session id (null で閉)
//
// 入れていないもの (= 派生制御 / 別性質):
//   - desktopOpen : visibilitychange 連動 (= App.jsx 側に残置)
//   - planOpen    : status.pending_plan 連動 auto-close (= App.jsx 側に残置)
//   - storageWarnDismissed : 表示状態 (= overlay でない)
//   - nowSec      : 表示用タイマー (= overlay でない、 F-12 で StatusBar 内部化予定)
import { useState } from 'react'

export function useOverlays() {
  const [drawer, setDrawer] = useState(false)
  const [menu, setMenu] = useState(false)
  const [favs, setFavs] = useState(false)
  const [tasks, setTasks] = useState(false)
  const [subagents, setSubagents] = useState(false)
  const [subagentsFocus, setSubagentsFocus] = useState(null)
  const [previewPath, setPreviewPath] = useState(null)
  const [treeOpen, setTreeOpen] = useState(null)
  const [confirmEnd, setConfirmEnd] = useState(false)
  const [confirmStop, setConfirmStop] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(null)
  return {
    drawer, setDrawer,
    menu, setMenu,
    favs, setFavs,
    tasks, setTasks,
    subagents, setSubagents,
    subagentsFocus, setSubagentsFocus,
    previewPath, setPreviewPath,
    treeOpen, setTreeOpen,
    confirmEnd, setConfirmEnd,
    confirmStop, setConfirmStop,
    confirmDelete, setConfirmDelete,
  }
}
