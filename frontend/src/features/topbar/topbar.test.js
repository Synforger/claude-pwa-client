// features/topbar の smoke contract (= ADR-026 Phase J-3、 新 features に対する snapshot 同梱)。
// node 環境 (= vitest config) で動かすため厳密な JSX render snapshot は本 file scope 外、
// 配線 entry の効果 (= featureRegistry に 'topbar' が register される) + default export 関数性を verify する。

import { describe, it, expect } from 'vitest'

describe('features/topbar — smoke contract', () => {
  it('Topbar.jsx は default export が関数 component', async () => {
    const mod = await import('./Topbar.jsx')
    expect(typeof mod.default).toBe('function')
  })

  it('index.js を import すると featureRegistry に \'topbar\' が register される', async () => {
    await import('./index.js')
    const reg = await import('../../registry/featureRegistry.js')
    expect(reg.list()).toContain('topbar')
  })
})
