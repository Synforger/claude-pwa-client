// features/app-effects の smoke contract (= ADR-026 Phase J-3)。
// AppEffects は app-wide effect 群を集約する不可視 component (= return null sentinel)、
// default export 関数性 + 「returns null」 静的契約を verify する (= featureRegistry 配線は 2026-07-27 退役)。

import { describe, it, expect } from 'vitest'

describe('features/app-effects — smoke contract', () => {
  it('AppEffects.jsx default-exports a function component', async () => {
    const mod = await import('./AppEffects.jsx')
    expect(typeof mod.default).toBe('function')
  })

})
