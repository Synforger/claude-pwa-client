// The length the client cuts a live tool result to is the length the backend cuts the history GET to
// (TOOL_RESULT_PREVIEW_CHARS in backend/jsonl/routes.py). A result that is cut the same way at both ends draws the same
// whether a conversation was received live or read again, so the two numbers are kept equal here.
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { TOOL_RESULT_PREVIEW_CHARS, TOOL_RESULT_DISPLAY_CHARS } from '../../src/_common/constants.js'

describe('tool result lengths', () => {
  it('the length kept in memory is the backend history length', () => {
    const source = readFileSync(new URL('../../../backend/jsonl/routes.py', import.meta.url), 'utf-8')
    const match = /^TOOL_RESULT_PREVIEW_CHARS\s*=\s*(\d+)/m.exec(source)
    expect(match, 'TOOL_RESULT_PREVIEW_CHARS is not found in backend/jsonl/routes.py').not.toBeNull()
    expect(TOOL_RESULT_PREVIEW_CHARS).toBe(Number(match[1]))
  })

  it('the length kept in memory is wider than the drawn length, so the drawn text does not change by the cut', () => {
    expect(TOOL_RESULT_PREVIEW_CHARS).toBeGreaterThan(TOOL_RESULT_DISPLAY_CHARS)
  })
})
