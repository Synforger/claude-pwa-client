import { getToolHandler } from '../tools/_registry.js'
import { truncate, SHORT_LABEL_MAX } from '../tools/_shared.js'

// formatTool は tool 名から tools/ 配下の handler を引き、 個別 format を呼ぶだけ。
// 表示の作り込みは各 handler (= frontend/src/tools/<family>.js の named export) 側に
// 閉じる。 新 tool を生やしたい時は対応 family file に 1 export + _registry.js に
// 1 行足すだけで配線完了 (= F-08 / F-57 registry 化)。
//
// registry に登録の無い tool 名は default 経路 (= MCP の mcp__<server>__<method> + その他
// 未知 tool) で「[displayName] <JSON>」 表示にフォールバック。
function defaultFormat(name, input) {
  const displayName = name.startsWith('mcp__')
    ? name.replace(/^mcp__/, '').replace(/__/g, '.')
    : name
  const label = `[${displayName}] ${JSON.stringify(input ?? {})}`
  const firstString = input && typeof input === 'object'
    ? Object.values(input).find(v => typeof v === 'string' && v.length > 0)
    : null
  const shortLabel = firstString
    ? `🔧 ${displayName} ${truncate(firstString, SHORT_LABEL_MAX - displayName.length - 4)}`
    : `🔧 ${displayName}`
  return { label, shortLabel }
}

export function formatTool(block) {
  const { id, name, input } = block
  const handler = getToolHandler(name)
  const out = handler ? handler.format(input) : defaultFormat(name, input)
  return {
    id,
    name,
    label: out.label ?? '',
    shortLabel: out.shortLabel ?? '',
    diffInput: out.diffInput ?? null,
    // Task / Agent の description は subagent の meta.description と一致するので、 🧩
    // スコープ表示の引き当てキーとして保持する (= タップで該当 agent の transcript に直行)。
    subagentDescription: out.subagentDescription ?? null,
  }
}

export function formatCost(usd) {
  if (usd == null || typeof usd !== 'number' || usd <= 0) return null
  if (usd < 0.001) return `$${usd.toFixed(5)}`
  if (usd < 0.01) return `$${usd.toFixed(4)}`
  return `$${usd.toFixed(3)}`
}

export function formatDuration(ms) {
  if (ms == null || typeof ms !== 'number' || ms <= 0) return null
  if (ms < 1000) return `${ms}ms`
  const sec = ms / 1000
  if (sec < 60) return `${sec.toFixed(1)}s`
  const m = Math.floor(sec / 60)
  const s = Math.round(sec - m * 60)
  return `${m}m${s}s`
}

function formatTokenCount(n) {
  if (n < 1000) return String(n)
  if (n < 10000) return (n / 1000).toFixed(1) + 'k'
  return Math.round(n / 1000) + 'k'
}

export function formatTokens(usage) {
  if (!usage || typeof usage !== 'object') return null
  const inp = usage.input_tokens || 0
  const out = usage.output_tokens || 0
  const cache = (usage.cache_read_input_tokens || 0) + (usage.cache_creation_input_tokens || 0)
  if (!inp && !out && !cache) return null
  const parts = []
  if (inp) parts.push(`in ${formatTokenCount(inp)}`)
  if (cache) parts.push(`cache ${formatTokenCount(cache)}`)
  if (out) parts.push(`out ${formatTokenCount(out)}`)
  return parts.join(' · ')
}

export function formatModelName(modelUsage) {
  if (!modelUsage || typeof modelUsage !== 'object') return null
  const key = Object.keys(modelUsage)[0]
  if (!key) return null
  // claude-opus-4-5-... → Opus / claude-sonnet-4-7-... → Sonnet のようにモデル系統名のみ
  // (バージョンまで出すと iPhone で折り返すため省略)
  const stripped = key.replace(/^claude-/, '')
  const parts = stripped.split('-')
  if (parts.length >= 1 && parts[0]) {
    return parts[0].charAt(0).toUpperCase() + parts[0].slice(1)
  }
  return key
}

// ANSI エスケープ (CSI m カラー等) を除去。Bash の `ls --color` などが ESC[...m を混ぜてくるので
// 表示前に落とす。OSC / DCS / その他のシーケンスもついでに最低限だけ除去。
// eslint-disable-next-line no-control-regex
const ANSI_CSI_RE = /\x1B\[[0-?]*[ -/]*[@-~]/g
// eslint-disable-next-line no-control-regex
const ANSI_OSC_RE = /\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)/g
// eslint-disable-next-line no-control-regex
const ANSI_OTHER_RE = /\x1B[@-Z\\-_]/g

export function stripAnsi(s) {
  if (typeof s !== 'string') return s
  return s.replace(ANSI_CSI_RE, '').replace(ANSI_OSC_RE, '').replace(ANSI_OTHER_RE, '')
}

export function formatToolResultContent(content) {
  if (content == null) return ''
  if (typeof content === 'string') return stripAnsi(content)
  if (Array.isArray(content)) {
    return content
      .map(b => {
        if (b?.type === 'text') return stripAnsi(b.text ?? '')
        if (b?.type === 'image') return '[画像]'
        // ToolSearch の result block: tool 名だけ抜き出す (= 旧経路では JSON.stringify
        // で生表示されてた)
        if (b?.type === 'tool_reference') return b.tool_name || '[tool_reference]'
        // 未知 type: 既知 human-readable field を優先して生 JSON 表示を避ける。
        // text / message / name / output 等が乗ってれば本文として扱う。
        if (typeof b?.text === 'string') return stripAnsi(b.text)
        if (typeof b?.message === 'string') return stripAnsi(b.message)
        if (typeof b?.output === 'string') return stripAnsi(b.output)
        if (typeof b?.name === 'string') return b.name
        return JSON.stringify(b)
      })
      .join('\n')
  }
  return JSON.stringify(content)
}

export function describeError(e) {
  if (!navigator.onLine) return 'オフライン'
  if (e?.name === 'TimeoutError') return 'タイムアウト'
  if (e instanceof TypeError) return 'ネットワークエラー（サーバーに接続できません）'
  if (e?.message) return `エラー: ${e.message}`
  return '送信失敗'
}

export function pctClass(pct) {
  if (pct >= 80) return 'pct red'
  if (pct >= 50) return 'pct yellow'
  return 'pct green'
}

export function timeUntil(unixSec, nowSec) {
  const now = nowSec ?? Date.now() / 1000
  let resetAt = unixSec
  if (resetAt < now) {
    const periods = Math.ceil((now - resetAt) / (5 * 3600))
    resetAt += periods * 5 * 3600
  }
  const diff = Math.max(0, resetAt - now)
  const h = Math.floor(diff / 3600)
  const m = Math.floor((diff % 3600) / 60)
  if (h > 0) return `${h}h${m}m`
  return `${m}m`
}

const WEEKDAYS_EN = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

// unix 秒の reset 時刻を「Sat 18:00」 形式で表示 (英略曜日 + HH:MM)。
// Anthropic の 7d window は **rolling 7-day** (= 最初の prompt から 7 日)、
// 固定曜日ではないので header から取った値で個人ごとに変わる時刻を表示する。
export function formatResetWeekdayTime(unixSec) {
  if (!unixSec) return ''
  const d = new Date(unixSec * 1000)
  const wd = WEEKDAYS_EN[d.getDay()]
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${wd} ${hh}:${mm}`
}
