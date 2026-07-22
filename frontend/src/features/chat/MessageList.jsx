// メッセージ一覧 + 「↓ 最新へ」 ボタン。 W2 Phase F-1 で AppShell.jsx の `<div className="messages">`
// 経路をそのまま物理移送 (= ロジック改変ゼロ、 displayMessages / scroll ref / handler は ChatPanel
// が解決して props 注入)。
//
// 旧 AppShell では .messages を `<div className="messages-container">` が囲み、 同じ container 内に
// Terminal LRU mount が absolute 配置されていた。 F-1 では Terminal mount は AppShell に残置、
// .messages のみ ChatPanel 配下に独立。 viewMode='terminal' 時の display:none gate は ChatPanel
// 側の hidden wrapper で実現する (= 旧 inline style と同等)。
import { useMemo } from 'react'
import MessageItem from './MessageItem.jsx'
import { useT } from '../../i18n/t.js'

// 表示を時系列 (= ts、 epoch ms) で安定ソートする。 メッセージは配列末尾 append で溜まるため、
// replay / GET / 遅延到着で古いメッセージが末尾に積まれると順番がバラバラに見える。 表示側で
// ts ソートすれば、 配列への入り方 (append 順) に依存せず常に正しい時系列で並ぶ (= 順序バグの
// 根治)。 ts を持たないメッセージ (= 楽観バブル確定前 / 一部 system marker) は直前の実効キーを
// 継いで時系列上の隣に留め、 元 index を tiebreak にして stable にする (= 同 ts の相対順維持)。
export function sortByTs(msgs) {
  let carry = -Infinity
  const keyed = msgs.map((m, i) => {
    const t = typeof m.ts === 'number' ? m.ts : null
    if (t != null) carry = t
    return { m, i, key: t != null ? t : carry }
  })
  keyed.sort((a, b) => (a.key - b.key) || (a.i - b.i))
  return keyed.map((x) => x.m)
}

export default function MessageList({
  scrollerDomRef,
  onScroll,
  viewMode,
  displayMessages,
  onOpenFile,
  apiKeySource,
  activeSubagentTool,
  onOpenSubagents,
  onFork,
  showScrollBtn,
  hasNew,
  scrollToBottom,
}) {
  const t = useT()
  // 表示直前に時系列ソート (= 順序バグ根治)。 displayMessages 参照が変わった時だけ再計算。
  const orderedMessages = useMemo(() => sortByTs(displayMessages || []), [displayMessages])
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
        {orderedMessages.map((msg) => (
          <MessageItem
            key={msg.id}
            msg={msg}
            onOpenFile={onOpenFile}
            apiKeySource={apiKeySource}
            activeSubagentTool={activeSubagentTool}
            onOpenSubagents={onOpenSubagents}
            onFork={onFork}
          />
        ))}
      </div>

      {viewMode !== 'terminal' && showScrollBtn && (
        <button className="scroll-btn" onClick={() => scrollToBottom()} aria-label={t('chat.scroll_latest')}>
          ↓
          {hasNew && <span className="scroll-dot" />}
        </button>
      )}
    </div>
  )
}
