// features/app-effects の smoke contract (= ADR-026 Phase J-3)。
// AppEffects は app-wide effect 群を集約する不可視 component (= return null sentinel)、
// default export 関数性 + featureRegistry 配線 + 「returns null」 静的契約を verify する。

import { describe, it, expect } from 'vitest'

describe('features/app-effects — smoke contract', () => {
  it('AppEffects.jsx default-exports a function component', async () => {
    const mod = await import('./AppEffects.jsx')
    expect(typeof mod.default).toBe('function')
  })

  it('importing index.js registers app-effects in featureRegistry', async () => {
    await import('./index.js')
    const reg = await import('../../registry/featureRegistry.js')
    expect(reg.list()).toContain('app-effects')
  })
})
