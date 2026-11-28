// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'

import { endComposition } from '../../../src/features/chat/endComposition.js'

function focusedField() {
  const field = document.createElement('textarea')
  document.body.appendChild(field)
  field.focus()
  const seen = []
  field.addEventListener('blur', () => seen.push('blur'))
  field.addEventListener('focus', () => seen.push('focus'))
  return { field, seen }
}

describe('endComposition', () => {
  it('takes the focus off a field with an open conversion and gives it back', () => {
    const { field, seen } = focusedField()
    expect(endComposition(field, true)).toBe(true)
    expect(seen).toEqual(['blur', 'focus'])
    expect(document.activeElement).toBe(field)
  })

  it('leaves a field without an open conversion alone', () => {
    const { field, seen } = focusedField()
    expect(endComposition(field, false)).toBe(false)
    expect(seen).toEqual([])
  })

  it('leaves a field that does not hold the focus alone', () => {
    const { field, seen } = focusedField()
    field.blur()
    seen.length = 0
    expect(endComposition(field, true)).toBe(false)
    expect(seen).toEqual([])
  })
})
