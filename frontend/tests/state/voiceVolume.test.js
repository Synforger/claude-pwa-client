import { describe, it, expect, afterEach, vi } from 'vitest'

// つまみの値は読み込んだ時に localStorage から決まるので、 試験ごとに置き場を作ってから読み直す
async function loadWith(entries, { inApp = false } = {}) {
  const store = new Map(Object.entries(entries))
  vi.stubGlobal('localStorage', {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(key, String(value)),
  })
  vi.stubGlobal('window', { Capacitor: { isNativePlatform: () => inApp } })
  vi.resetModules()
  const volume = await import('../../src/state/voiceVolume.js')
  return { volume, store }
}

describe('voiceVolume', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('keeps the value it stored', async () => {
    const { volume } = await loadWith({ cpc_v3_voice_volume: '0.4' }, { inApp: true })
    expect(volume.getSnapshot().volume).toBe(0.4)
  })

  it('carries the value from before the call gain over in the browser', async () => {
    const { volume } = await loadWith({ cpc_v2_voice_volume: '0.7' })
    expect(volume.getSnapshot().volume).toBe(0.7)
  })

  it('starts the app over at 100% instead of the value from before the call gain', async () => {
    const { volume } = await loadWith({ cpc_v2_voice_volume: '0.05' }, { inApp: true })
    expect(volume.getSnapshot().volume).toBe(1)
  })

  it('stores a new value under the new key', async () => {
    const { volume, store } = await loadWith({})
    volume.setVoiceVolume(0.35)
    expect(store.get('cpc_v3_voice_volume')).toBe('0.35')
  })
})
