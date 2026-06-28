// system kind ごとの inline カード集約。 各コンポーネントは `msg` 1 件分の object を
// 受けて純表示するのみ。 messageRegistry の Render field から参照され、 MessageItem 側の
// system kind switch を generic lookup (= `Entry.Render`) に置換する設計 (= F-04 consumer)。
//
// 切り出し方針:
// - 旧 MessageItem.jsx 内に並んでた CompactBanner / SessionEndBanner / ApiErrorCard /
//   AttachmentCard / HookErrorCard / SystemNoteCard をそのままこの 1 ファイルに集約する
//   (= 1 ファイル 7 サブコンポーネント、 後で機能ごとに分けたい時に細分化しやすい単位)。
// - TaskNotification は元から専用ファイルなので registry 側で直接 import する。
// - format helper (= formatDuration) は utils/format.js から引く。
import { formatDuration } from '../../utils/format.js'

// 会話圧縮 (compact_boundary) 用バナー。SDK からは事後通知しか来ないので
// 「圧縮完了」の表示のみ。pre→post のトークン減少と所要時間を添える。
function formatCompactTokens(n) {
  if (n == null) return null
  if (n < 1000) return String(n)
  if (n < 10000) return (n / 1000).toFixed(1) + 'k'
  return Math.round(n / 1000) + 'k'
}

export function CompactBanner({ msg }) {
  const parts = []
  if (msg.trigger) parts.push(msg.trigger)
  if (msg.preTokens != null && msg.postTokens != null) {
    parts.push(`${formatCompactTokens(msg.preTokens)} → ${formatCompactTokens(msg.postTokens)} tokens`)
  }
  const dur = formatDuration(msg.durationMs)
  if (dur) parts.push(dur)
  const detail = parts.length > 0 ? ` (${parts.join(' · ')})` : ''
  return (
    <div className="message system compact-banner">
      <span className="compact-line">
        <span className="compact-rule" />
        <span className="compact-label">会話を圧縮しました{detail}</span>
        <span className="compact-rule" />
      </span>
    </div>
  )
}

export function SessionEndBanner() {
  // 「セッション終了」 を区切る横線 + ラベル。 旧 chat UI と同じ見た目。
  return (
    <div className="message system compact-banner">
      <span className="compact-line">
        <span className="compact-rule" />
        <span className="compact-label">セッション終了</span>
        <span className="compact-rule" />
      </span>
    </div>
  )
}

export function ApiErrorCard({ msg }) {
  const retrySec = typeof msg.retryInMs === 'number' && msg.retryInMs > 0
    ? `${(msg.retryInMs / 1000).toFixed(1)}s 後にリトライ`
    : null
  const attempt = typeof msg.retryAttempt === 'number' && msg.retryAttempt > 0
    ? `(${msg.retryAttempt} 回目)`
    : null
  return (
    <div className="message system api-error-card">
      <div className="api-error-header">
        <span className="api-error-icon">⚠️</span>
        <span className="api-error-title">{msg.isNetworkDown ? 'ネットワーク切断' : `API エラー${msg.status ? ` (${msg.status})` : ''}`}</span>
      </div>
      <div className="api-error-body">{msg.formatted}</div>
      {(retrySec || attempt || msg.requestId) && (
        <div className="api-error-meta">
          {retrySec && <span>{retrySec}</span>}
          {attempt && <span>{attempt}</span>}
          {msg.requestId && <span className="api-error-req">{msg.requestId}</span>}
        </div>
      )}
    </div>
  )
}

function attachmentShort(sub, a) {
  switch (sub) {
    case 'edited_text_file':       return `📎 edited file  ${a.filename || ''}`
    case 'file':                   return `📎 attached file  ${a.filename || ''}`
    case 'compact_file_reference': return `📎 compact ref  ${a.displayPath || a.filename || ''}`
    case 'queued_command':         return `📎 queued  ${a.content || a.command || ''}`
    case 'task_reminder':          return `📎 task reminder  ${a.itemCount ?? ''}`
    case 'skill_listing':          return `📎 skills  ${Array.isArray(a.skills) ? `${a.skills.length} available` : ''}`
    case 'command_permissions':    return `📎 perms  ${Array.isArray(a.allowedTools) ? `${a.allowedTools.length} tools` : ''}`
    case 'auto_mode':              return `📎 auto mode`
    default:                       return `📎 ${sub}`
  }
}

export function AttachmentCard({ msg }) {
  const a = msg.attachment || {}
  const short = attachmentShort(msg.subtype, a)
  const body = JSON.stringify(a, null, 2)
  return (
    <div className="message system attachment-card">
      <details>
        <summary><span className="tool-line tool-attach">{short}</span></summary>
        <pre className="attachment-body">{body}</pre>
      </details>
    </div>
  )
}

export function HookErrorCard({ msg }) {
  const dur = msg.durationMs != null ? `${msg.durationMs}ms` : null
  const short = `⚠️ hook failed  ${msg.hookName || '(unknown)'}${msg.exitCode != null ? `  exit ${msg.exitCode}` : ''}`
  return (
    <div className="message system hook-error-card">
      <details>
        <summary><span className="tool-line tool-hook-error">{short}</span></summary>
        {msg.command && <pre className="hook-error-block"><b>command:</b> {msg.command}</pre>}
        {msg.stderr && <pre className="hook-error-block"><b>stderr:</b> {msg.stderr}</pre>}
        {msg.stdout && <pre className="hook-error-block"><b>stdout:</b> {msg.stdout}</pre>}
        {dur && <pre className="hook-error-block"><b>durationMs:</b> {dur}</pre>}
      </details>
    </div>
  )
}

export function SystemNoteCard({ msg }) {
  const short = ({
    local_command: 'ℹ slash command',
    scheduled_task_fire: 'ℹ scheduled wakeup',
  })[msg.subtype] || `ℹ ${msg.subtype}`
  return (
    <div className="message system system-note-card">
      <details>
        <summary><span className="tool-line tool-system-note">{short}</span></summary>
        <pre className="attachment-body">{msg.content || '(empty)'}</pre>
      </details>
    </div>
  )
}
