// TodoWrite + Plan 系 (ExitPlanMode / EnterPlanMode)。 表示専用 (= UI 側で進捗を可視化)。
import { truncate, SHORT_LABEL_MAX } from './_shared.js'

export const TodoWrite = {
  format(input) {
    const todos = Array.isArray(input?.todos) ? input.todos : []
    const n = todos.length
    const doing = todos.filter(t => t?.status === 'in_progress').length
    const done = todos.filter(t => t?.status === 'completed').length
    const shortLabel = doing > 0
      ? `📋 ${n} todos (${doing} doing)`
      : done === n && n > 0
        ? `📋 ${n} todos (all done)`
        : `📋 ${n} todos`
    const lines = todos.map(t => {
      const mark = t?.status === 'completed' ? '✓'
        : t?.status === 'in_progress' ? '◉'
        : '○'
      return `  ${mark} ${t?.content ?? ''}`
    })
    return { label: `todo update (${n} items)\n${lines.join('\n')}`, shortLabel }
  },
}

export const ExitPlanMode = {
  format(input) {
    const plan = (input?.plan ?? '').toString()
    const firstLine = plan.split('\n').find(l => l.trim()) || ''
    return {
      label: `plan:\n${plan}`,
      shortLabel: `📑 plan: ${truncate(firstLine, SHORT_LABEL_MAX - 10)}`,
    }
  },
}

export const EnterPlanMode = {
  format() {
    return {
      label: `enter plan mode (= read-only, no edits until ExitPlanMode)`,
      shortLabel: `📑 plan mode ON`,
    }
  },
}
