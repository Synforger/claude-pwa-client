import { describe, expect, it } from 'vitest'
import { tierLabel } from './tierLabel.js'

describe('tierLabel', () => {
  it('shows the last name of the tier', () => {
    expect(tierLabel('projects/エージェントプラットフォーム')).toBe('エージェントプラットフォーム')
    expect(tierLabel('projects/alpha/subprojects/beta')).toBe('beta')
  })

  it('shows normal as normal', () => {
    expect(tierLabel('normal')).toBe('normal')
  })

  it('shows nothing when the tier is not known', () => {
    expect(tierLabel(null)).toBeNull()
    expect(tierLabel(undefined)).toBeNull()
    expect(tierLabel('')).toBeNull()
    expect(tierLabel('/')).toBeNull()
  })
})
