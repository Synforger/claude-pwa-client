// Web 系 (WebSearch / WebFetch)。 query / url を short に出し、 詳細は展開時に出す。
import { truncate } from './_shared.js'

export const WebSearch = {
  format(input) {
    const q = input?.query ?? ''
    const shortLabel = truncate(`search "${q}"`)
    const lines = [`search "${q}"`]
    if (Array.isArray(input?.allowed_domains) && input.allowed_domains.length > 0) {
      lines.push(`  allowed: ${input.allowed_domains.join(', ')}`)
    }
    if (Array.isArray(input?.blocked_domains) && input.blocked_domains.length > 0) {
      lines.push(`  blocked: ${input.blocked_domains.join(', ')}`)
    }
    return { label: lines.join('\n'), shortLabel }
  },
}

export const WebFetch = {
  format(input) {
    const url = input?.url ?? ''
    const shortLabel = truncate(`fetch ${url}`)
    const lines = [`fetch ${url}`]
    if (input?.prompt) {
      lines.push('', `prompt:`, input.prompt)
    }
    return { label: lines.join('\n'), shortLabel }
  },
}
