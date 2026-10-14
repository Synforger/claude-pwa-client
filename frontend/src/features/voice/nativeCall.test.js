import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

vi.mock('../../transport/http.ts', () => ({ apiFetch: vi.fn() }))
vi.mock('./audio.js', () => ({ unlockAudio: vi.fn(), playSound: vi.fn() }))
vi.mock('./conversation.js', () => ({ openConversation: vi.fn() }))

const { apiFetch } = await import('../../transport/http.ts')
const { openConversation } = await import('./conversation.js')
const { toggleVoice, toggleMic, closeConversation, observeVoiceEvent, changeVolume, _resetForTest: resetVoice } = await import('./voice.js')
const { getSnapshot: volumeOf, setVoiceVolume } = await import('../../state/voiceVolume.js')
const { getSnapshot, setVoiceAvailable, setVoiceListen, _resetForTest } = await import('../../state/voice.js')

const { API_BASE } = await import('../../constants.js')

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))

// app の native の部品 (= BackgroundVoice) の代わり。 呼ばれた口を記録し、 知らせを手で流せる。
let plugin
let notify
beforeEach(() => {
  _resetForTest()
  resetVoice()
  apiFetch.mockReset()
  apiFetch.mockImplementation(async () => ({ ok: true, status: 200, json: async () => ({}) }))
  openConversation.mockReset()
  plugin = {
    start: vi.fn(async () => {}),
    setMic: vi.fn(async () => {}),
    stop: vi.fn(async () => {}),
    addListener: vi.fn((event, callback) => { notify = callback }),
  }
  vi.stubGlobal('window', {
    location: { href: 'https://host.example/' },
    Capacitor: { isNativePlatform: () => true, Plugins: { BackgroundVoice: plugin } },
  })
  setVoiceAvailable('ses_a', true)
  setVoiceListen('ses_a', true)
})
afterEach(() => vi.unstubAllGlobals())

describe('inside the iPhone app, the app holds the microphone and the voice', () => {
  it('opens a call to the tab instead of listening in the screen, with the microphone off', async () => {
    toggleVoice('ses_a', vi.fn())
    expect(getSnapshot().on.ses_a).toBe(true)
    expect(getSnapshot().phase.ses_a).toBeUndefined()
    await settle()
    const url = new URL(`${API_BASE}/sessions/ses_a/voice/call?volume=1`, 'https://host.example/').href
    expect(plugin.start).toHaveBeenCalledWith({ url, mic: false })
    expect(openConversation).not.toHaveBeenCalled()
    notify({ state: 'connected' })
    expect(getSnapshot().phase.ses_a).toBeUndefined()
  })

  it('starts the next call with the microphone on, when it was left on', async () => {
    toggleVoice('ses_a', vi.fn())
    await settle()
    toggleMic('ses_a', vi.fn())
    closeConversation('ses_a')
    toggleVoice('ses_a', vi.fn())
    expect(getSnapshot().phase.ses_a).toBe('starting')
    await settle()
    expect(plugin.start).toHaveBeenLastCalledWith(expect.objectContaining({ mic: true }))
    notify({ state: 'connected' })
    expect(getSnapshot().phase.ses_a).toBe('listening')
  })

  it('does not say the replies in the screen while the call says them', async () => {
    toggleVoice('ses_a', vi.fn())
    await settle()
    const reply = { type: 'assistant', uuid: 'u1', ts: Date.now() + 1000, message: { content: [{ type: 'text', text: '晴れです。' }] } }
    observeVoiceEvent('ses_a', reply)
    await settle()
    expect(apiFetch.mock.calls.filter(([path]) => path.endsWith('/voice/utterances'))).toHaveLength(0)
  })

  it('turns the microphone in the app on and off, and the voice keeps playing', async () => {
    toggleVoice('ses_a', vi.fn())
    await settle()
    toggleMic('ses_a', vi.fn())
    expect(plugin.setMic).toHaveBeenLastCalledWith({ on: true })
    expect(getSnapshot().phase.ses_a).toBe('listening')
    toggleMic('ses_a', vi.fn())
    expect(plugin.setMic).toHaveBeenLastCalledWith({ on: false })
    expect(getSnapshot().phase.ses_a).toBeUndefined()
    expect(getSnapshot().on.ses_a).toBe(true)
  })

  it('hangs up when the voice is turned off, and when the backend ends the call', async () => {
    toggleVoice('ses_a', vi.fn())
    await settle()
    closeConversation('ses_a')
    expect(plugin.stop).toHaveBeenCalledTimes(1)
    expect(getSnapshot().on.ses_a).toBeUndefined()

    toggleVoice('ses_a', vi.fn())
    await settle()
    notify({ state: 'disconnected' })
    expect(plugin.stop).toHaveBeenCalledTimes(2)
    expect(getSnapshot().on.ses_a).toBeUndefined()
  })

  it('shows why when the call could not be made', async () => {
    toggleVoice('ses_a', vi.fn())
    await settle()
    notify({ state: 'error', message: 'microphone denied' })
    expect(getSnapshot().on.ses_a).toBeUndefined()
    expect(getSnapshot().error.ses_a).toBe('microphone denied')
  })

  it('keeps the screen conversation for an agent that only speaks', async () => {
    setVoiceListen('ses_a', false)
    toggleVoice('ses_a', vi.fn())
    await settle()
    expect(plugin.start).not.toHaveBeenCalled()
    expect(getSnapshot().on.ses_a).toBe(true)
  })

  it('passes this device\'s volume to the call, and a new volume while the call is open', async () => {
    setVoiceVolume(0.6)
    toggleVoice('ses_a', vi.fn())
    await settle()
    expect(plugin.start.mock.calls[0][0].url).toMatch(/[?&]volume=0\.6$/)
    changeVolume('ses_a', 1.35)
    const posted = apiFetch.mock.calls.filter(([path]) => path.endsWith('/voice/call/volume'))
    expect(posted.map(([, opts]) => opts.jsonBody)).toEqual([{ volume: 1.35 }])
    setVoiceVolume(1)
  })

  it('keeps the volume between 0 and 2', () => {
    setVoiceVolume(5)
    expect(volumeOf().volume).toBe(2)
    setVoiceVolume(-1)
    expect(volumeOf().volume).toBe(0)
    setVoiceVolume(1)
  })
})
