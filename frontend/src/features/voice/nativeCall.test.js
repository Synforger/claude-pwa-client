import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

vi.mock('../../transport/http.ts', () => ({ apiFetch: vi.fn() }))
vi.mock('./audio.js', () => ({ unlockAudio: vi.fn(), playSound: vi.fn() }))
vi.mock('./conversation.js', () => ({ openConversation: vi.fn() }))

const { apiFetch } = await import('../../transport/http.ts')
const { openConversation } = await import('./conversation.js')
const {
  toggleVoice, toggleMic, closeConversation, observeVoiceEvent, changeVolume, hasAppCall, showCallPicture,
  _resetForTest: resetVoice,
} = await import('./voice.js')
const { getSnapshot: volumeOf, setVoiceVolume } = await import('../../state/voiceVolume.js')
const { getSnapshot, setVoiceAvailable, setVoiceListen, _resetForTest } = await import('../../state/voice.js')

const { API_BASE } = await import('../../constants.js')

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))

// app の native の部品 (= BackgroundVoice) の代わり。 呼ばれた口を記録し、 知らせを手で流せる。
let plugin
let listeners
// app の state の知らせ (= 受け手を種類ごとに覚える偽の app の、 state の受け手を呼ぶ)
const notify = (data) => listeners.state?.(data)
beforeEach(() => {
  _resetForTest()
  resetVoice()
  apiFetch.mockReset()
  apiFetch.mockImplementation(async () => ({ ok: true, status: 200, json: async () => ({}) }))
  openConversation.mockReset()
  listeners = {}
  plugin = {
    start: vi.fn(async () => {}),
    setMic: vi.fn(async () => {}),
    setSpeech: vi.fn(async () => {}),
    showPicture: vi.fn(async () => {}),
    stop: vi.fn(async () => {}),
    addListener: vi.fn((event, callback) => { listeners[event] = callback }),
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

  it('starts a call with the microphone on and the voice off from the microphone alone', async () => {
    toggleMic('ses_a', vi.fn())
    expect(getSnapshot().phase.ses_a).toBe('starting')
    await settle()
    expect(plugin.start).toHaveBeenLastCalledWith(expect.objectContaining({ mic: true }))
    expect(plugin.start.mock.calls.at(-1)[0].url).toContain('speech=0')
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

  it('keeps the call when the app reports an error the call survives, and shows why', async () => {
    toggleVoice('ses_a', vi.fn())
    await settle()
    // app 1.9.0 が実際に渡した文 (= Pipecat の error を Swift の文字列のまま。 2026-10-14 23:42)
    notify({
      state: 'error',
      message: 'RTVIMessageInbound(id: nil, label: Optional("rtvi-ai"), type: Optional("error"), data: Optional("'
        + '{\\"fatal\\":false,\\"error\\":\\"TTS context 2b42b5f4 completed with no audio\\"}"))',
    })
    expect(plugin.stop).not.toHaveBeenCalled()
    expect(getSnapshot().on.ses_a).toBe(true)
    expect(getSnapshot().error.ses_a).toBe('TTS context 2b42b5f4 completed with no audio')

    notify({ state: 'error', message: 'a sentence failed', fatal: false })
    expect(plugin.stop).not.toHaveBeenCalled()
    expect(getSnapshot().error.ses_a).toBe('a sentence failed')

    notify({ state: 'error', message: 'the call broke', fatal: true })
    expect(plugin.stop).toHaveBeenCalledTimes(1)
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

  it('follows the microphone switched from the PiP window, so the 🎙 shows the same', async () => {
    toggleVoice('ses_a', vi.fn())
    await settle()
    notify({ state: 'connected' })
    listeners.mic({ on: true })
    expect(getSnapshot().phase.ses_a).toBe('listening')
    toggleMic('ses_a', vi.fn())   // 🎙 を押すと、 小窓で入れたマイクを切る
    expect(plugin.setMic).toHaveBeenLastCalledWith({ on: false })
    listeners.mic({ on: true })
    listeners.mic({ on: false })
    expect(getSnapshot().phase.ses_a).toBeUndefined()
    listeners.mic({})             // 形の違う知らせは見ない
    expect(getSnapshot().phase.ses_a).toBeUndefined()
  })

  it('turns the agent voice off and on in the call while the microphone stays, and an old app just ends the call', async () => {
    toggleVoice('ses_a', vi.fn())
    await settle()
    toggleMic('ses_a', vi.fn())
    toggleVoice('ses_a', vi.fn())
    expect(getSnapshot().quiet.ses_a).toBe(true)
    await settle()
    expect(plugin.setSpeech).toHaveBeenLastCalledWith({ on: false })
    toggleVoice('ses_a', vi.fn())
    expect(getSnapshot().quiet.ses_a).toBeUndefined()
    expect(plugin.setSpeech).toHaveBeenLastCalledWith({ on: true })
    delete plugin.setSpeech                       // 声の入 / 切の口を持たない古い版の app
    toggleVoice('ses_a', vi.fn())
    await settle()
    expect(plugin.stop).toHaveBeenCalled()
    expect(getSnapshot().on.ses_a).toBeUndefined()
  })

  it('shows the picture-in-picture on request only while the tab has a call, and says why when it cannot', async () => {
    expect(hasAppCall('ses_a')).toBe(false)
    showCallPicture('ses_a')
    expect(plugin.showPicture).not.toHaveBeenCalled()
    toggleVoice('ses_a', vi.fn())
    await settle()
    expect(hasAppCall('ses_a')).toBe(true)
    const show = plugin.showPicture
    delete plugin.showPicture                     // 小窓で表示の口を持たない古い版の app には出さない
    expect(hasAppCall('ses_a')).toBe(false)
    plugin.showPicture = show
    plugin.showPicture.mockRejectedValueOnce(new Error('picture in picture is not possible now'))
    showCallPicture('ses_a')
    await settle()
    expect(plugin.showPicture).toHaveBeenCalledTimes(1)
    expect(getSnapshot().error.ses_a).toBe('picture in picture is not possible now')
  })
})
