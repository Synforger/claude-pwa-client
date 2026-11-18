// API tabs (`src/_common/apiTab.js`): how the screen tells one, and how the context amount and the spend read.
import { describe, it, expect } from 'vitest'
import { API_KIND, formatContextTokens, formatMoney, formatSpend, isApiTab, isApiTabId } from '../../src/_common/apiTab.js'

describe('isApiTab / isApiTabId', () => {
  it('tells an API tab by the kind of its row, and a Claude tab (which has no kind) is not one', () => {
    expect(isApiTab({ id: 'api_support-bot', kind: API_KIND })).toBe(true)
    expect(isApiTab({ id: 'ses_abc' })).toBe(false)
    expect(isApiTab({ id: 'ses_abc', kind: 'claude' })).toBe(false)
    expect(isApiTab(null)).toBe(false)
    expect(isApiTab(undefined)).toBe(false)
  })

  it('tells an API tab id by its prefix, for the places that hold no row', () => {
    expect(isApiTabId('api_support-bot')).toBe(true)
    expect(isApiTabId('ses_0123456789ab')).toBe(false)
    expect(isApiTabId('')).toBe(false)
    expect(isApiTabId(null)).toBe(false)
  })
})

describe('formatContextTokens', () => {
  it.each([
    [0, '0'], [950, '950'], [999, '999'], [1000, '1.0k'], [2300, '2.3k'], [9999, '10.0k'], [12300, '12.3k'], [123456, '123.5k'],
  ])('writes %d as %s', (tokens, text) => {
    expect(formatContextTokens(tokens)).toBe(text)
  })

  it('writes nothing for an amount that is not known (never 0)', () => {
    for (const unknown of [null, undefined, NaN, -1, '12', Infinity]) expect(formatContextTokens(unknown)).toBeNull()
  })
})

describe('formatSpend / formatMoney', () => {
  it('writes the spend against the limit in the wallet currency', () => {
    expect(formatSpend({ spent: 123, limit: 1000, currency: 'JPY' })).toBe('123 / 1,000 JPY')
    expect(formatSpend({ spent: 0, limit: 50, currency: 'USD' })).toBe('0 / 50 USD')
    expect(formatSpend({ spent: 12.345, limit: 100.5, currency: 'USD' })).toBe('12.35 / 100.50 USD')
  })

  it('writes nothing when the wallet has no figure (the file is missing, broken or of another month)', () => {
    expect(formatSpend(null)).toBeNull()
    expect(formatSpend(undefined)).toBeNull()
    expect(formatSpend({ spent: 'a lot', limit: 1, currency: 'JPY' })).toBeNull()
  })

  it('keeps cents only for an amount that has them', () => {
    expect(formatMoney(1234, 'JPY')).toBe('1,234 JPY')
    expect(formatMoney(1234.5, 'USD')).toBe('1,234.50 USD')
  })
})
