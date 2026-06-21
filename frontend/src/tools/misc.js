// 単発系 (PushNotification / NotebookEdit / RemoteTrigger / Skill / ToolSearch /
// ShareOnboardingGuide)。 1 ファイルに収めるほど近しくはないが、 専用 file を切るほど
// 関連 tool も無いため共通の「その他」 file にまとめる。
import { truncate, SHORT_LABEL_MAX } from './_shared.js'

export const PushNotification = {
  format(input) {
    const msg = input?.message ?? ''
    return {
      label: `push notification:\n${msg}`,
      shortLabel: `🔔 push ${truncate(msg, SHORT_LABEL_MAX - 8)}`,
    }
  },
}

export const NotebookEdit = {
  format(input) {
    const p = input?.notebook_path ?? ''
    const base = p.split('/').pop()
    const mode = input?.edit_mode || 'replace'
    const lines = [`path: ${p}`, `mode: ${mode}`]
    if (input?.cell_id) lines.push(`cell_id: ${input.cell_id}`)
    if (input?.cell_type) lines.push(`cell_type: ${input.cell_type}`)
    return {
      label: lines.join('\n'),
      shortLabel: `notebook ${mode}  ${truncate(base, SHORT_LABEL_MAX - 12)}`,
    }
  },
}

export const RemoteTrigger = {
  format(input) {
    const action = input?.action ?? '?'
    const tid = input?.trigger_id ?? ''
    const lines = [`action: ${action}`]
    if (tid) lines.push(`trigger_id: ${tid}`)
    if (input?.body) lines.push('', 'body:', JSON.stringify(input.body, null, 2))
    return {
      label: lines.join('\n'),
      shortLabel: `🔗 remote ${action}${tid ? ' ' + tid : ''}`,
    }
  },
}

export const Skill = {
  format(input) {
    const s = input?.skill ?? '?'
    const args = input?.args ?? ''
    return {
      label: `/${s}${args ? ' ' + args : ''}`,
      shortLabel: `⚡ skill /${s}${args ? ' ' + truncate(args, SHORT_LABEL_MAX - s.length - 10) : ''}`,
    }
  },
}

export const ToolSearch = {
  format(input) {
    const q = input?.query ?? ''
    return {
      label: `tool search: ${q}` + (input?.max_results ? `\nmax_results: ${input.max_results}` : ''),
      shortLabel: `🔍 tool search ${truncate(q, SHORT_LABEL_MAX - 16)}`,
    }
  },
}

export const ShareOnboardingGuide = {
  format(input) {
    const mode = input?.mode || 'check'
    let label = `share onboarding guide, mode=${mode}`
    if (input?.short_code) label += `, short_code=${input.short_code}`
    return {
      label,
      shortLabel: `📤 share onboarding (${mode})`,
    }
  },
}
