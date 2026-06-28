// terminal 領域 (= Terminal + on-screen keyboard + Ctrl-* ボタン)。
// 中身の component は features/terminal / features/ios-native が Phase F で実装、 ここでは slot のみ。

export default function TerminalPane({ sid }) {
  return (
    <div className="cpc-terminal-pane" data-sid={sid}>
      {/* features/terminal (= Phase F で実装、 xterm.js + WS /ws/pty/{sid}) */}
      <div className="cpc-terminal-slot" data-feature="terminal" />
      {/* features/terminal 内の Ctrl-* quick buttons */}
      <div className="cpc-control-buttons-slot" data-feature="terminal-controls" />
      {/* features/ios-native の on-screen keyboard (= mobile detect で表示) */}
      <div className="cpc-keyboard-slot" data-feature="ios-keyboard" />
    </div>
  )
}
