// 添付ファイルの chip 列。 W2 Phase F-1 で AppShell.jsx から物理移送 (= ロジック改変ゼロ)。
// useAttachments 自体は ChatPanel が呼出し (= ChatInput と同 hook instance を共有して二重 state
// を避ける)、 本 component は currentAttachments / removeAttachment を props 経由で受ける。
export default function AttachmentsBar({ activeSid, currentAttachments, removeAttachment }) {
  if (!currentAttachments || currentAttachments.length === 0) return null
  return (
    <div className="attachments-bar" data-testid="attachments-bar">
      {currentAttachments.map((item, i) => (
        <div key={i} className="attach-chip">
          {item.url ? (
            <img src={item.url} className="attach-thumb" alt="" />
          ) : (
            <span className="attach-name">📄 {item.file.name}</span>
          )}
          <button className="attach-remove" onClick={() => removeAttachment(activeSid, i)} aria-label="添付を削除">×</button>
        </div>
      ))}
    </div>
  )
}
