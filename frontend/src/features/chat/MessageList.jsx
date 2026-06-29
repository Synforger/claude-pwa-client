// メッセージ一覧 + 「↓ 最新へ」 ボタン。 W2 Phase F-1 で AppShell.jsx の `<div className="messages">`
// 経路をそのまま物理移送 (= ロジック改変ゼロ、 displayMessages / scroll ref / handler は ChatPanel
// が解決して props 注入)。
//
// 旧 AppShell では .messages を `<div className="messages-container">` が囲み、 同じ container 内に
// Terminal LRU mount が absolute 配置されていた。 F-1 では Terminal mount は AppShell に残置、
// .messages のみ ChatPanel 配下に独立。 viewMode='terminal' 時の display:none gate は ChatPanel
// 側の hidden wrapper で実現する (= 旧 inline style と同等)。
import MessageItem from './MessageItem.jsx'

export default function MessageList({
  scrollerDomRef,
  onScroll,
  viewMode,
  displayMessages,
  onOpenFile,
  onAnswer,
  apiKeySource,
  activeSubagentTool,
  onOpenSubagents,
  onFork,
  showScrollBtn,
  hasNew,
  scrollToBottom,
}) {
  // .messages-container は scroll-btn (= position: absolute) の基準点 (= position: relative)。
  // 旧 AppShell では Terminal LRU mount もここに同居していたが、 F-1 で .messages + scroll-btn
  // だけが本 component 配下に残った。 wrapper を外すと scroll-btn が祖先 (= .app or body) を
  // 基準にして画面外 / 右下端に飛ぶ regression が出るので、 .messages-container は必ず維持する。
  return (
    <div className="messages-container">
      {/* chat も Terminal と対称に mount しっぱなしで display 切替する。
          terminal モードへ行っても DOM が unmount されないので、 戻った時に
          scroll 位置 / 画像 / プレビューの内部状態がそのまま残る (= 2026-06-16)。 */}
      <div
        ref={scrollerDomRef}
        className="messages"
        onScroll={onScroll}
        style={viewMode === 'terminal' ? { display: 'none' } : undefined}
      >
        {displayMessages.map((msg) => (
          <MessageItem
            key={msg.id}
            msg={msg}
            onOpenFile={onOpenFile}
            onAnswer={onAnswer}
            apiKeySource={apiKeySource}
            activeSubagentTool={activeSubagentTool}
            onOpenSubagents={onOpenSubagents}
            onFork={onFork}
          />
        ))}
      </div>

      {viewMode !== 'terminal' && showScrollBtn && (
        <button className="scroll-btn" onClick={() => scrollToBottom()} aria-label="最新メッセージへ">
          ↓
          {hasNew && <span className="scroll-dot" />}
        </button>
      )}
    </div>
  )
}
