// 子 agent / workflow / question 系 (AskUserQuestion / Monitor / Agent / Task / Workflow)。
// Agent と Task は旧 SDK / 現行 SDK の名前差異なので同じ shape で扱う。
import { truncate, SHORT_LABEL_MAX } from './_shared.js'

export const AskUserQuestion = {
  format(input) {
    // 専用バブル (AskUserQuestionBubble) で UI 提示してるので、 tool-log では簡略のみ。
    const questions = Array.isArray(input?.questions) ? input.questions : []
    const first = questions[0]
    const q = first?.question ?? ''
    const headers = questions.map(qq => qq?.header || qq?.question || '').filter(Boolean)
    return {
      label: `ask user: ${questions.length} question(s)\n${headers.map(h => `  • ${h}`).join('\n')}`,
      shortLabel: `❓ ${truncate(q, SHORT_LABEL_MAX - 4)}`,
    }
  },
}

export const Monitor = {
  format(input) {
    const desc = input?.description ?? ''
    const cmd = input?.command ?? ''
    const lines = []
    if (desc) lines.push(`description: ${desc}`)
    if (cmd) lines.push('', 'command:', cmd)
    if (input?.timeout_ms) lines.push('', `timeout: ${input.timeout_ms}ms`)
    if (input?.persistent) lines.push(`persistent: true`)
    return {
      label: lines.join('\n'),
      shortLabel: `👁 monitor ${truncate(desc || cmd, SHORT_LABEL_MAX - 12)}`,
    }
  },
}

// 旧 SDK は 'Agent'、 現行 SDK (Claude Code) は 'Task' で来る。 同じ input schema:
//   { description, prompt, subagent_type, model?, isolation?, run_in_background? }
// 名前差異だけ吸収して同じ表示にする。 = サブエージェントへの依頼内容 (description /
// prompt) を tool-log で「ちゃんと投げた」 が一目で分かるように、 詳細展開で全 prompt
// も見られる形に揃える。
function formatAgent(input) {
  const desc = input?.description ?? ''
  const sub = input?.subagent_type ?? 'general-purpose'
  const lines = [`agent: ${sub}`, `description: ${desc}`]
  if (input?.model) lines.push(`model: ${input.model}`)
  if (input?.isolation) lines.push(`isolation: ${input.isolation}`)
  if (input?.run_in_background) lines.push(`background: true`)
  // prompt 本文は chat 側で非表示 (= 🤖 chip → subagent panel に詳細経路あり、
  // inline 展開で全文出すと長文で会話が埋もれる、 2026-06-20)
  if (input?.prompt) lines.push('', `prompt: ${input.prompt.length} chars (= 🤖 から開く)`)
  return {
    label: lines.join('\n'),
    shortLabel: `🤖 agent[${sub}] ${truncate(desc, SHORT_LABEL_MAX - sub.length - 12)}`,
    subagentDescription: desc || null,
  }
}

export const Agent = { format: formatAgent }
export const Task = { format: formatAgent }

export const Workflow = {
  format(input) {
    const wfName = input?.name || input?.scriptPath || '(inline script)'
    const lines = [`workflow: ${wfName}`]
    if (input?.args !== undefined) lines.push('', 'args:', JSON.stringify(input.args, null, 2))
    return {
      label: lines.join('\n'),
      shortLabel: `🔀 workflow ${truncate(wfName, SHORT_LABEL_MAX - 12)}`,
    }
  },
}
