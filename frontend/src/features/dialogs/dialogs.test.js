// features/dialogs の smoke contract (= ADR-026 Phase J-3)。
// 3 confirm dialog (= End / Stop / Delete) の default export 関数性 + overlayRegistry 配線確認。

import { describe, it, expect } from 'vitest'

describe('features/dialogs — smoke contract', () => {
  it('ConfirmEndDialog.jsx は default export が関数 component', async () => {
    const mod = await import('./ConfirmEndDialog.jsx')
    expect(typeof mod.default).toBe('function')
  })

  it('ConfirmStopDialog.jsx は default export が関数 component', async () => {
    const mod = await import('./ConfirmStopDialog.jsx')
    expect(typeof mod.default).toBe('function')
  })

  it('ConfirmDeleteDialog.jsx は default export が関数 component', async () => {
    const mod = await import('./ConfirmDeleteDialog.jsx')
    expect(typeof mod.default).toBe('function')
  })

  it('index.js を import すると overlayRegistry に 3 confirm dialog 全部が Component spec 付きで register される', async () => {
    await import('./index.js')
    const reg = await import('../../registry/overlayRegistry.js')
    const keys = reg.list()
    expect(keys).toContain('confirmEnd')
    expect(keys).toContain('confirmStop')
    expect(keys).toContain('confirmDelete')
    // Component lazy spec が設定されてる (= OverlayHost 経由 render の前提)
    for (const key of ['confirmEnd', 'confirmStop', 'confirmDelete']) {
      const entry = reg.describe(key)
      expect(entry).toBeTruthy()
      expect(typeof entry.Component).toBe('function')
    }
  })
})
