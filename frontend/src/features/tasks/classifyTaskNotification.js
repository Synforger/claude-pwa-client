// TaskNotification (= `<task-notification>` harness event) の summary 文字列を type 別に分類する
// pure helper。 実 harness session 観測サンプル:
//   - Agent \"...\" finished                             → subagent
//   - Background command \"...\" completed (exit code N) → background bash
//   - Monitor event: \"...\"                             → monitor
//   - それ以外                                            → unknown (raw output 表示に fallback)
//
// 型に応じて card icon + click 時に開く modal を変える。 判別は summary の先頭パターンだけ見るので
// 安定 (= 本文中に "Agent \"" が偶然登場しても命中しない、 命名スキーマは harness 固有)。

const AGENT_RE = /^Agent [\\]?"/
const BASH_RE = /^Background command [\\]?"/
const MONITOR_RE = /^Monitor event: [\\]?"/

/**
 * @param {string|null|undefined} summary
 * @returns {'agent' | 'bash' | 'monitor' | 'unknown'}
 */
export function classifyTaskNotification(summary) {
  if (typeof summary !== 'string' || !summary) return 'unknown'
  if (AGENT_RE.test(summary)) return 'agent'
  if (BASH_RE.test(summary)) return 'bash'
  if (MONITOR_RE.test(summary)) return 'monitor'
  return 'unknown'
}

/** icon: 型別に card 表示を切り分ける。 error 色は card 側で is-error 上書き。 */
export function iconForTaskType(type) {
  switch (type) {
    case 'agent': return '🤖'
    case 'bash': return '⚙'
    case 'monitor': return '👁'
    default: return '⚙'
  }
}
