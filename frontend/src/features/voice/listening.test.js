import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

vi.mock('../../transport/http.ts', () => ({ apiFetch: vi.fn() }))
vi.mock('./audio.js', () => ({ unlockAudio: vi.fn(), playSound: vi.fn() }))

const { apiFetch } = await import('../../transport/http.ts')
const { pressMic, cancelListening } = await import('./voice.js')
const { startRecording } = await import('./recorder.js')
const { getSnapshot, setVoiceListen, setVoiceAvailable, _resetForTest } = await import('../../state/voice.js')

// 作り物のマイク: 開いた回数と、 閉じた track を数える。 録った音は 'speech' の 1 片。
function fakeMedia({ refuse = false } = {}) {
  const media = { opened: 0, closed: 0 }
  media.open = async () => {
    if (refuse) throw new Error('Permission denied')
    media.opened += 1
    return { getTracks: () => [{ stop: () => { media.closed += 1 } }] }
  }
  media.Recorder = class {
    constructor() { this.state = 'inactive'; this.mimeType = 'audio/webm;codecs=opus' }
    start() { this.state = 'recording' }
    stop() {
      this.state = 'inactive'
      this.ondataavailable({ data: new Blob(['speech'], { type: 'audio/webm' }) })
      this.onstop()
    }
  }
  return media
}

const heard = (text) => ({ ok: true, json: async () => ({ text }) })
const settle = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('startRecording — one sound from the microphone', () => {
  it('gives back what was recorded, in the browser\'s own format, and closes the microphone', async () => {
    const media = fakeMedia()
    const recording = await startRecording(media)
    const sound = await recording.stop()
    expect(sound.type).toBe('audio/webm;codecs=opus')
    expect(await sound.text()).toBe('speech')
    expect(media.closed).toBe(1)
  })

  it('closes the microphone when it is let go without a sound', async () => {
    const media = fakeMedia()
    const recording = await startRecording(media)
    await recording.cancel()
    expect(media.closed).toBe(1)
  })
})

describe('pressMic — press to speak, press again to send', () => {
  beforeEach(() => {
    _resetForTest()
    apiFetch.mockReset()
    setVoiceAvailable('ses_a', true)
    setVoiceListen('ses_a', 110)
  })
  afterEach(() => vi.useRealTimers())

  it('turns the voice on, records, and sends what was heard to the tab', async () => {
    const media = fakeMedia()
    const send = vi.fn()
    await pressMic('ses_a', send, media)
    expect(getSnapshot().on.ses_a).toBe(true)
    expect(getSnapshot().listening.ses_a).toBe('recording')

    apiFetch.mockResolvedValue(heard('明日の予定を教えて'))
    await pressMic('ses_a', send, media)
    const [path, opts] = apiFetch.mock.calls[0]
    expect(path).toBe('/sessions/ses_a/voice/transcription')
    expect(opts.method).toBe('POST')
    expect(opts.headers).toEqual({ 'Content-Type': 'audio/webm;codecs=opus' })
    expect(await opts.body.text()).toBe('speech')
    expect(send).toHaveBeenCalledWith('明日の予定を教えて')
    expect(getSnapshot().listening.ses_a).toBeUndefined()
    expect(getSnapshot().error.ses_a).toBeUndefined()
    expect(media.closed).toBe(1)
  })

  it('sends nothing when no speech was heard, and says so', async () => {
    const send = vi.fn()
    await pressMic('ses_a', send, fakeMedia())
    apiFetch.mockResolvedValue(heard('  '))
    await pressMic('ses_a', send, fakeMedia())
    expect(send).not.toHaveBeenCalled()
    expect(getSnapshot().error.ses_a).toBeTruthy()
    expect(getSnapshot().listening.ses_a).toBeUndefined()
  })

  it('says why when the microphone cannot be opened', async () => {
    await pressMic('ses_a', vi.fn(), fakeMedia({ refuse: true }))
    expect(getSnapshot().error.ses_a).toContain('Permission denied')
    expect(getSnapshot().listening.ses_a).toBeUndefined()
  })

  it('says why when the backend refuses the sound', async () => {
    const send = vi.fn()
    await pressMic('ses_a', send, fakeMedia())
    apiFetch.mockResolvedValue({ ok: false, status: 502, json: async () => ({ detail: { code: 'voice_listen_unreachable' } }) })
    await pressMic('ses_a', send, fakeMedia())
    expect(send).not.toHaveBeenCalled()
    expect(getSnapshot().error.ses_a).toBeTruthy()
  })

  it('does not send what was said in a tab that was left while it was being heard', async () => {
    const send = vi.fn()
    await pressMic('ses_a', send, fakeMedia())
    let answer
    apiFetch.mockReturnValue(new Promise((resolve) => { answer = resolve }))
    const finishing = pressMic('ses_a', send, fakeMedia())
    await settle()
    expect(getSnapshot().listening.ses_a).toBe('hearing')
    await cancelListening('ses_a')
    answer(heard('送られない'))
    await finishing
    expect(send).not.toHaveBeenCalled()
  })

  it('ignores a press while what was said is being heard', async () => {
    const send = vi.fn()
    await pressMic('ses_a', send, fakeMedia())
    let answer
    apiFetch.mockReturnValue(new Promise((resolve) => { answer = resolve }))
    const finishing = pressMic('ses_a', send, fakeMedia())
    await settle()
    await pressMic('ses_a', send, fakeMedia())
    expect(apiFetch).toHaveBeenCalledTimes(1)
    answer(heard('一度だけ'))
    await finishing
    expect(send).toHaveBeenCalledTimes(1)
  })

  it('stops recording by itself at the longest it may listen, and sends', async () => {
    vi.useFakeTimers()
    setVoiceListen('ses_a', 2)
    const send = vi.fn()
    await pressMic('ses_a', send, fakeMedia())
    apiFetch.mockResolvedValue(heard('長い話'))
    await vi.advanceTimersByTimeAsync(2000)
    expect(send).toHaveBeenCalledWith('長い話')
  })

  it('lets go of a microphone that has not opened yet when pressed again, and closes it once it opens', async () => {
    const media = fakeMedia()
    let opened
    const open = media.open
    media.open = () => new Promise((resolve) => { opened = () => resolve(open()) })
    const first = pressMic('ses_a', vi.fn(), media)
    await settle()
    expect(getSnapshot().listening.ses_a).toBe('recording')
    await pressMic('ses_a', vi.fn(), media)
    expect(getSnapshot().listening.ses_a).toBeUndefined()
    opened()
    await first
    expect(media.closed).toBe(1)
    expect(apiFetch).not.toHaveBeenCalled()
  })

  it('closes the microphone when the tab is left while recording', async () => {
    const media = fakeMedia()
    await pressMic('ses_a', vi.fn(), media)
    await cancelListening('ses_a')
    expect(media.closed).toBe(1)
    expect(getSnapshot().listening.ses_a).toBeUndefined()
    expect(apiFetch).not.toHaveBeenCalled()
  })
})
