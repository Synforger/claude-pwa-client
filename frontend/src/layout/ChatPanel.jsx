// chat 領域 (= MessageList + ChatInput + StatusBar + ActivityBar の組立)。
// 中身の component は features/chat / features/status-bar / features/tasks / features/plan-approval が
// Phase F で実装、 ここでは slot レイアウトのみ定義。

export default function ChatPanel({ sid }) {
  return (
    <div className="cpc-chat-panel" data-sid={sid}>
      {/* features/status-bar (= Phase F で実装) */}
      <div className="cpc-status-slot" data-feature="status-bar" />
      {/* features/plan-approval / tasks の ActivityBar */}
      <div className="cpc-activity-slot" data-feature="activity-bar" />
      {/* features/chat の MessageList */}
      <div className="cpc-messages-slot" data-feature="chat-messages" />
      {/* features/chat の ChatInput */}
      <div className="cpc-input-slot" data-feature="chat-input" />
    </div>
  )
}
