// The settings card of a program that lists API tabs (`apiSourceDraft.js`): what it holds and what it sends.
import { describe, it, expect } from 'vitest'
import { sourceDraftOf, sourcePatch } from '../../../src/features/settings/apiSourceDraft.js'

const source = {
  id: 'line-group',
  fields: [
    { key: 'monthly_budget_usd', label: '月の予算', unit: 'USD', min: 1, max: 1000, step: 1, default: 100 },
    { key: 'idle_hours', label: '静か', unit: '時間', min: 0.5, max: 48, step: 0.5, default: 6 },
    { key: 'offset', label: 'ずれ', unit: null, min: -5, max: 5, step: null, default: 0 },
  ],
  values: { monthly_budget_usd: 100, idle_hours: 6, offset: 0 },
}

describe('sourceDraftOf', () => {
  it('holds each value as text, and the default where the file has none', () => {
    expect(sourceDraftOf({ ...source, values: { monthly_budget_usd: 50 } }))
      .toEqual({ monthly_budget_usd: '50', idle_hours: '6', offset: '0' })
  })
})

describe('sourcePatch', () => {
  const draft = sourceDraftOf(source)

  it('sends nothing while nothing changed', () => {
    expect(sourcePatch(source, draft)).toEqual({ values: null, invalid: [] })
  })

  it('sends only the values that changed, as numbers', () => {
    expect(sourcePatch(source, { ...draft, idle_hours: '1.5', offset: '-2.25' }))
      .toEqual({ values: { idle_hours: 1.5, offset: -2.25 }, invalid: [] })
  })

  it('names a value out of the range, off the grid or not a number, and sends none of it', () => {
    expect(sourcePatch(source, { ...draft, monthly_budget_usd: '2000' }).invalid).toEqual(['monthly_budget_usd'])
    expect(sourcePatch(source, { ...draft, idle_hours: '1.25' }).invalid).toEqual(['idle_hours'])
    expect(sourcePatch(source, { ...draft, offset: 'abc' }).invalid).toEqual(['offset'])
    expect(sourcePatch(source, { ...draft, offset: '' }).invalid).toEqual(['offset'])
  })
})
