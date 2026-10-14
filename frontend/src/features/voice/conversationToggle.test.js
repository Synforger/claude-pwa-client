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

let mic
beforeEach(() => {
  _resetForTest()
  apiFetch.mockReset()
  apiFetch.mockResolvedValue(ok())
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
  })

  it('sends what was heard to the tab, naming this screen as the holder', async () => {
    const send = vi.fn()
    toggleConversation('ses_a', send)
    await settle()
    const { hear } = openConversation.mock.calls[0][0]
    const client = calls('POST', '/voice/conversation')[0][1].jsonBody.client
    apiFetch.mockResolvedValue(ok({ text: ' 明日の予定は？ ' }))
    await hear(new Blob(['wav'], { type: 'audio/wav' }))
    const [, opts] = calls('POST', '/voice/transcription')[0]
    expect(opts.headers).toEqual({ 'Content-Type': 'audio/wav', 'X-Voice-Conversation': client })
    expect(send).toHaveBeenCalledWith('明日の予定は？')
  })

  it('drops a sound that was not speech, without a word', async () => {
    const send = vi.fn()
    toggleConversation('ses_a', send)
    await settle()
    apiFetch.mockResolvedValue(ok({ text: '' }))
    await openConversation.mock.calls[0][0].hear(new Blob(['wav']))
    expect(send).not.toHaveBeenCalled()
    expect(getSnapshot().error.ses_a).toBeUndefined()
  })

  it('closes, and says so, when another screen has opened the conversation', async () => {
    toggleConversation('ses_a', vi.fn())
    await settle()
    apiFetch.mockResolvedValue({ ok: false, status: 409, json: async () => ({ detail: { code: 'voice_conversation_elsewhere' } }) })
    await openConversation.mock.calls[0][0].hear(new Blob(['wav']))
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
    setVoiceTurn('ses_a', false)
    toggleConversation('ses_a', vi.fn())
    await settle()
    expect(openConversation.mock.calls[0][0].turnModelUrl).toBeNull()
  })
})
