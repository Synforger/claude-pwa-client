// terminal 領域 (= Terminal + on-screen keyboard + Ctrl-* ボタン) の常時 mount owner
// (= W2 Phase F-2、 2026-06-29)。
//
// ChatPanel と同様 always-mount + 内部 display:none gate 方式を採用 (= viewMode='terminal' 経験
// sid の xterm.js / WS lifecycle を chat 切替で失わない)。 LRU 管理 + Terminal 本体描画は
// features/terminal/TerminalMount.jsx が担当、 本 file は flex sizing + display gate の薄い
// wrapper のみ。
//
// 旧 stub (= phase E 時点の slot プレースホルダ) を物理置換、 旧 cpc-terminal-pane / data-sid 属性は
// 互換のため残す (= 現状 CSS / test ref なしだが将来 e2e / 視覚 regression 用の hook として保持)。

import { useSyncExternalStore } from 'react'
import TerminalMount from '../features/terminal/TerminalMount.jsx'
import { subscribe as subscribeUi, getSnapshot as getUiSnapshot } from '../state/ui.js'

export default function TerminalPane({ sid }) {
  // viewMode は state/ui.js から自前 pull (= AppShell に props drilling させない)。 sid が null の
  // 時は 'chat' で固定し display:none、 active 切替で TerminalMount が LRU を回す。
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  const activeViewMode = sid ? (ui.viewModes[sid] || 'chat') : 'chat'
  const hidden = activeViewMode !== 'terminal'

  return (
    <div
      className="cpc-terminal-pane"
      data-sid={sid || ''}
      style={{
        position: 'relative',
        flex: 1,
        minHeight: 0,
        display: hidden ? 'none' : 'block',
      }}
    >
      <TerminalMount sid={sid} />
    </div>
  )
}
