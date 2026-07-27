// features/topbar の smoke contract (= ADR-026 Phase J-3、 新 features に対する snapshot 同梱)。
// node 環境 (= vitest config) で動かすため厳密な JSX render snapshot は本 file scope 外、
// default export 関数性を verify する (= featureRegistry 配線は 2026-07-27 退役)。

import { describe, it, expect } from 'vitest'

describe('features/topbar — smoke contract', () => {
  it('Topbar.jsx default-exports a function component', async () => {
    const mod = await import('./Topbar.jsx')
    expect(typeof mod.default).toBe('function')
  })

})
