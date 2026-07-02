// transcript 1 event を軽量描画する (= 親 chat の MessageItem 完全再現はしない、 要点だけ)。
// SubagentsModal と TaskNotification 両方から使う共有 renderer。 元は SubagentsModal 内に閉じ
// ていたが、 <task-notification> の output-file が subagent jsonl symlink 化 (= Claude Code 側
// 仕様変化) された事を受けて TaskNotification からも同じ transcript 表示を出したくなった
// ため、 dedup ではなく単一 source として本 file に集約した (= PRs #48/#49)。
import MessageRenderer from '../chat/MessageRenderer.jsx'
import { formatTool } from '../../utils/format.js'

export default function TranscriptEvent({ event }) {
  if (event.type === 'user_message') {
    return (
      <div className="sa-ev sa-ev-user">
        <span className="sa-ev-role">▸ prompt</span>
        <div className="sa-ev-text"><MessageRenderer text={event.text || ''} /></div>
      </div>
    )
  }
  if (event.type === 'assistant') {
    const content = event.message?.content || []
    const texts = content.filter(b => b.type === 'text').map(b => b.text).join('')
    const thinking = content.filter(b => b.type === 'thinking').map(b => b.thinking).join('\n')
    const tools = content
      .filter(b => b.type === 'tool_use' && b.name !== 'AskUserQuestion')
      .map(b => formatTool(b))
    return (
      <div className="sa-ev sa-ev-agent">
        {thinking && <div className="sa-ev-thinking">{thinking}</div>}
        {texts && <div className="sa-ev-text"><MessageRenderer text={texts} /></div>}
        {tools.map(t => (
          <div key={t.id} className="sa-ev-tool">{t.shortLabel || t.name}</div>
        ))}
      </div>
    )
  }
  return null
}
