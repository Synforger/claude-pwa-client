// Cron + ScheduleWakeup 系。 cron は schedule + prompt、 wakeup は delay + reason。
import { truncate, SHORT_LABEL_MAX } from './_shared.js'

export const CronCreate = {
  format(input) {
    const cron = input?.cron ?? ''
    const prompt = input?.prompt ?? ''
    const lines = [`schedule: ${cron}`]
    if (input?.recurring === false) lines.push('recurring: false (one-shot)')
    if (input?.durable) lines.push('durable: true (survives restart)')
    if (prompt) lines.push('', 'prompt:', prompt)
    return {
      label: lines.join('\n'),
      shortLabel: `⏰ cron[${cron}] ${truncate(prompt, SHORT_LABEL_MAX - cron.length - 12)}`,
    }
  },
}

export const CronDelete = {
  format(input) {
    return {
      label: `delete cron job id=${input?.id ?? '?'}`,
      shortLabel: `⏰ cron del ${input?.id ?? '?'}`,
    }
  },
}

export const CronList = {
  format() {
    return { label: `list all scheduled cron jobs`, shortLabel: `⏰ cron list` }
  },
}

export const ScheduleWakeup = {
  format(input) {
    const sec = input?.delaySeconds ?? '?'
    const reason = input?.reason ?? ''
    const lines = [`delay: ${sec}s`, `reason: ${reason}`]
    if (input?.prompt) lines.push('', 'prompt:', input.prompt)
    return {
      label: lines.join('\n'),
      shortLabel: `⏰ wakeup +${sec}s ${truncate(reason, SHORT_LABEL_MAX - 16)}`,
    }
  },
}
