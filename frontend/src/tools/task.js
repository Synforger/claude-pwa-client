// background task (TaskOutput / TaskStop) と user-side task tracker (TaskCreate /
// TaskUpdate / TaskGet / TaskList)。 名前空間が衝突気味だが SDK 由来でこのまま入る。
import { truncate, SHORT_LABEL_MAX } from './_shared.js'

export const TaskOutput = {
  format(input) {
    const tid = input?.task_id ?? '?'
    return {
      label: `get output of task ${tid}` + (input?.block ? ` (blocking)` : ` (non-blocking)`),
      shortLabel: `🤖 task output ${tid.slice(0, 12)}`,
    }
  },
}

export const TaskStop = {
  format(input) {
    const tid = input?.task_id ?? input?.shell_id ?? '?'
    return {
      label: `stop background task ${tid}`,
      shortLabel: `🤖 task stop ${tid.slice(0, 12)}`,
    }
  },
}

export const TaskCreate = {
  format(input) {
    const subj = input?.subject ?? ''
    const lines = [`create task: ${subj}`]
    if (input?.description) lines.push('', input.description)
    return {
      label: lines.join('\n'),
      shortLabel: `📋 task + ${truncate(subj, SHORT_LABEL_MAX - 10)}`,
    }
  },
}

export const TaskUpdate = {
  format(input) {
    const tid = input?.taskId ?? '?'
    const st = input?.status
    const lines = [`update task ${tid}`]
    if (st) lines.push(`status: ${st}`)
    if (input?.subject) lines.push(`subject: ${input.subject}`)
    if (input?.description) lines.push('', input.description)
    return {
      label: lines.join('\n'),
      shortLabel: st ? `📋 task #${tid} → ${st}` : `📋 task #${tid} update`,
    }
  },
}

export const TaskGet = {
  format(input) {
    return {
      label: `get task ${input?.taskId ?? '?'}`,
      shortLabel: `📋 task get #${input?.taskId ?? '?'}`,
    }
  },
}

export const TaskList = {
  format(input) {
    const filt = input?.status ? ` (status=${input.status})` : ''
    return {
      label: `list tasks${filt}`,
      shortLabel: `📋 task list${filt}`,
    }
  },
}
