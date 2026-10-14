import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('../../transport/http.ts', () => ({ apiFetch: vi.fn() }))
vi.mock('./audio.js', () => ({ unlockAudio: vi.fn(), playSound: vi.fn() }))
vi.mock('./conversation.js', () => ({ openConversation: vi.fn() }))

const { apiFetch } = await import('../../transport/http.ts')
const { openConversation } = await import('./conversation.js')
const { toggleConversation } = await import('./voice.js')
const { getSnapshot, setVoiceAvailable, setVoiceListen, setVoiceTurn, _resetForTest } = await import('../../state/voice.js')

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))
const ok = (body = {}) => ({ ok: true, status: 200, json: async () => body, arrayBuffer: async () => new ArrayBuffer(1) })

const CONVERSATION = { pause_ms: 700, wait_ms: 3000, unfinished_endings: ['、'], interrupt: true }
let mic
let voiceInfo
beforeEach(() => {
  _resetForTest()
  apiFetch.mockReset()
  voiceInfo = { enabled: true, marks: [], default: '', listen: true, turn: true, conversation: CONVERSATION, tuning_error: '' }
  // GET /voice はその時の voiceInfo を、 他の口は空の 200 を返す
  apiFetch.mockImplementation(async (path, opts) => (path.endsWith('/voice') && !opts?.method ? ok(voiceInfo) : ok()))
  openConversation.mockReset()
  openConversation.mockImplementation(async () => ({ close: vi.fn(async () => {}) }))
  mic = { stopped: 0, refuse: null }
  globalThis.AudioContext = class { close() { return Promise.resolve() } }
  // Node 20 には navigator が無い (= 21 から在る)。 voice.js が読むのはマイクだけなので、 それだけの物に差し替える
  vi.stubGlobal('navigator', {
    mediaDevices: {
      getUserMedia: async () => {
        if (mic.refuse) throw Object.assign(new Error('Permission denied'), { name: mic.refuse })
        return { getTracks: () => [{ stop: () => { mic.stopped += 1 } }] }
      },
    },
  })
  setVoiceAvailable('ses_a', true)
  setVoiceListen('ses_a', true)
  setVoiceTurn('ses_a', true)
})

const calls = (method, suffix) => apiFetch.mock.calls.filter(([path, opts]) => path.endsWith(suffix) && (opts?.method || 'GET') === method)

describe('toggleConversation — one button opens and closes the conversation', () => {
  it('opens: the voice plays, this screen holds the conversation, and the turn model is handed over', async () => {
    toggleConversation('ses_a', vi.fn())
    expect(getSnapshot().on.ses_a).toBe(true)
    expect(getSnapshot().phase.ses_a).toBe('starting')
    await settle()
    const [claim] = calls('POST', '/voice/conversation')
    expect(claim[1].jsonBody.client).toMatch(/^screen-[a-z0-9]+$/)
    expect(openConversation).toHaveBeenCalledTimes(1)
    const deps = openConversation.mock.calls[0][0]
    expect(deps.turnModelUrl).toBe('/sessions/ses_a/voice/turn-model')
    expect(deps.audioContext).toBeInstanceOf(AudioContext)
    expect(deps.settings).toEqual(CONVERSATION)
  })

  it('reads the pauses again each time it opens, so what the agent changed counts from the next time', async () => {
    toggleConversation('ses_a', vi.fn())
    await settle()
    toggleConversation('ses_a', vi.fn())
    await settle()
    voiceInfo = { ...voiceInfo, conversation: { ...CONVERSATION, pause_ms: 900 } }
    toggleConversation('ses_a', vi.fn())
    await settle()
    expect(openConversation.mock.calls[1][0].settings.pause_ms).toBe(900)
  })

  it('stops the reply that is playing when the speaker cuts in', async () => {
    toggleConversation('ses_a', vi.fn())
    await settle()
    expect(() => openConversation.mock.calls[0][0].interrupt()).not.toThrow()
    expect(getSnapshot().speaking.ses_a).toBeUndefined()
  })

  it('sends what was heard to the tab, naming this screen as the holder', async () => {
    const send = vi.fn()
    toggleConversation('ses_a', send)
    await settle()
    const deps = openConversation.mock.calls[0][0]
    const client = calls('POST', '/voice/conversation')[0][1].jsonBody.client
    apiFetch.mockResolvedValue(ok({ text: ' 明日の予定は？ ' }))
    const text = await deps.transcribe(new Blob(['wav'], { type: 'audio/wav' }))
    const [, opts] = calls('POST', '/voice/transcription')[0]
    expect(opts.headers).toEqual({ 'Content-Type': 'audio/wav', 'X-Voice-Conversation': client })
    expect(text).toBe('明日の予定は？')
    deps.send(text)
    expect(send).toHaveBeenCalledWith('明日の予定は？')
  })

  it('writes a sound that was not speech down as nothing, without a word', async () => {
    toggleConversation('ses_a', vi.fn())
    await settle()
    apiFetch.mockResolvedValue(ok({ text: '' }))
    expect(await openConversation.mock.calls[0][0].transcribe(new Blob(['wav']))).toBe('')
    expect(getSnapshot().error.ses_a).toBeUndefined()
  })

  it('sends nothing once it is closed', async () => {
    const send = vi.fn()
    toggleConversation('ses_a', send)
    await settle()
    const deps = openConversation.mock.calls[0][0]
    toggleConversation('ses_a', vi.fn())
    deps.send('遅れて届いた文')
    expect(send).not.toHaveBeenCalled()
  })

  it('closes, and says so, when another screen has opened the conversation', async () => {
    toggleConversation('ses_a', vi.fn())
    await settle()
    apiFetch.mockResolvedValue({ ok: false, status: 409, json: async () => ({ detail: { code: 'voice_conversation_elsewhere' } }) })
    expect(await openConversation.mock.calls[0][0].transcribe(new Blob(['wav']))).toBe('')
    expect(getSnapshot().on.ses_a).toBeUndefined()
    expect(getSnapshot().error.ses_a).toBeTruthy()
  })

  it('closes on a second press: the microphone, the conversation, and the voice', async () => {
    toggleConversation('ses_a', vi.fn())
    await settle()
    const handle = await openConversation.mock.results[0].value
    apiFetch.mockClear()
    toggleConversation('ses_a', vi.fn())
    await settle()
    expect(handle.close).toHaveBeenCalled()
    expect(calls('DELETE', '/voice/conversation')).toHaveLength(1)
    expect(mic.stopped).toBe(1)
    expect(getSnapshot().on.ses_a).toBeUndefined()
    expect(getSnapshot().phase.ses_a).toBeUndefined()
  })

  it('only turns the voice on and off for an agent that does not listen', async () => {
    setVoiceListen('ses_a', false)
    toggleConversation('ses_a', vi.fn())
    await settle()
    expect(getSnapshot().on.ses_a).toBe(true)
    expect(openConversation).not.toHaveBeenCalled()
    expect(calls('POST', '/voice/conversation')).toHaveLength(0)
    toggleConversation('ses_a', vi.fn())
    expect(getSnapshot().on.ses_a).toBeUndefined()
  })

  it('says why when the microphone is refused, and stays closed', async () => {
    mic.refuse = 'NotAllowedError'
    toggleConversation('ses_a', vi.fn())
    await settle(); await settle()
    expect(getSnapshot().on.ses_a).toBeUndefined()
    expect(getSnapshot().error.ses_a).toContain('Permission denied')
    expect(openConversation).not.toHaveBeenCalled()
  })

  it('hands over no turn model when the agent has none', async () => {
    voiceInfo = { ...voiceInfo, turn: false }
    setVoiceTurn('ses_a', false)
    toggleConversation('ses_a', vi.fn())
    await settle()
    expect(openConversation.mock.calls[0][0].turnModelUrl).toBeNull()
  })
})
