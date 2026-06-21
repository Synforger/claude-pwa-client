// EnterWorktree / ExitWorktree。 worktree 作成 / 退出 (isolation 用)。
import { truncate, SHORT_LABEL_MAX } from './_shared.js'

export const EnterWorktree = {
  format(input) {
    const what = input?.name || input?.path || '(auto-named)'
    const lines = [`isolated worktree`]
    if (input?.name) lines.push(`name: ${input.name}`)
    if (input?.path) lines.push(`path: ${input.path}`)
    return {
      label: lines.join('\n'),
      shortLabel: `🌳 worktree ${truncate(what, SHORT_LABEL_MAX - 14)}`,
    }
  },
}

export const ExitWorktree = {
  format(input) {
    const action = input?.action ?? '?'
    const lines = [`action: ${action}`]
    if (input?.discard_changes) lines.push('discard_changes: true')
    return {
      label: lines.join('\n'),
      shortLabel: `🌳 worktree exit ${action}`,
    }
  },
}
