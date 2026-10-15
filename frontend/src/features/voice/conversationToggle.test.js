import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('../../transport/http.ts', () => ({ apiFetch: vi.fn() }))
vi.mock('./audio.js', () => ({ unlockAudio: vi.fn(), playSound: vi.fn() }))
vi.mock('./conversation.js', () => ({ openConversation: vi.fn() }))

const { apiFetch } = await import('../../transport/http.ts')
const { openConversation } = await import('./conversation.js')
const { toggleVoice, toggleMic, startCall, setVoiceSender, voiceOnSids, _resetForTest: resetVoice } = await import('./voice.js')
const { getSnapshot, setVoiceAvailable, setVoiceListen, setVoiceTurn, _resetForTest } = await import('../../state/voice.js')

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))
const ok = (body = {}) => ({ ok: true, status: 200, json: async () => body, arrayBuffer: async () => new ArrayBuffer(1) })

const CONVERSATION = { pause_ms: 700, wait_ms: 3000, unfinished_endings: ['、'], interrupt: true }
let mic
let voiceInfo
beforeEach(() => {
  _resetForTest()
  resetVoice()
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

// 声をオンにしてから 🎙 でマイクを開く (= 声をオンにしただけでは、 マイクを取らない)。 send は聞き取った文の送り手
function talk(send = vi.fn(), sid = 'ses_a') {
  setVoiceSender(send)
  toggleVoice(sid)
  toggleMic(sid)
}

// 声もマイクも切って、 会話を終える (= talk の後)
function hangUp(sid = 'ses_a') {
  toggleVoice(sid)
  toggleMic(sid)
}

const calls = (method, suffix) => apiFetch.mock.calls.filter(([path, opts]) => path.endsWith(suffix) && (opts?.method || 'GET') === method)

describe('toggleVoice / toggleMic — the voice, and the microphone inside it', () => {
  it('plays the voice without taking the microphone until the microphone is pressed', async () => {
    let asked = 0
    navigator.mediaDevices.getUserMedia = async () => { asked += 1; return { getTracks: () => [] } }
    toggleVoice('ses_a', vi.fn())
    await settle()
    expect(getSnapshot().on.ses_a).toBe(true)
    expect(getSnapshot().phase.ses_a).toBeUndefined()
    expect(asked).toBe(0)
    expect(calls('POST', '/voice/conversation')).toHaveLength(0)
    expect(openConversation).not.toHaveBeenCalled()
  })

  it('opens: the voice plays, this screen holds the conversation, and the turn model is handed over', async () => {
    toggleVoice('ses_a', vi.fn())
    toggleMic('ses_a', vi.fn())
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
    talk(vi.fn())
    await settle()
    hangUp()
    await settle()
    voiceInfo = { ...voiceInfo, conversation: { ...CONVERSATION, pause_ms: 900 } }
    talk(vi.fn())
    await settle()
    expect(openConversation.mock.calls[1][0].settings.pause_ms).toBe(900)
  })

  it('stops the reply that is playing when the speaker cuts in', async () => {
    talk(vi.fn())
    await settle()
    expect(() => openConversation.mock.calls[0][0].interrupt()).not.toThrow()
    expect(getSnapshot().speaking.ses_a).toBeUndefined()
  })

  it('sends what was heard to the tab, naming this screen as the holder', async () => {
    const send = vi.fn()
    talk(send)
    await settle()
    const deps = openConversation.mock.calls[0][0]
    const client = calls('POST', '/voice/conversation')[0][1].jsonBody.client
    apiFetch.mockResolvedValue(ok({ text: ' 明日の予定は？ ' }))
    const text = await deps.transcribe(new Blob(['wav'], { type: 'audio/wav' }))
    const [, opts] = calls('POST', '/voice/transcription')[0]
    expect(opts.headers).toEqual({ 'Content-Type': 'audio/wav', 'X-Voice-Conversation': client })
    expect(text).toBe('明日の予定は？')
    deps.send(text)
    expect(send).toHaveBeenCalledWith('ses_a', '明日の予定は？')
  })

  it('keeps one tab in the voice: turning it on in another tab closes the first', async () => {
    setVoiceAvailable('ses_b', true)
    setVoiceListen('ses_b', true)
    const send = vi.fn()
    talk(send)
    await settle()
    const first = await openConversation.mock.results[0].value
    expect(voiceOnSids()).toBe('ses_a')
    talk(send, 'ses_b')
    await settle()
    expect(first.close).toHaveBeenCalled()
    expect(getSnapshot().on.ses_a).toBeUndefined()
    expect(voiceOnSids()).toBe('ses_b')
    // 聞き取った文は、 その会話のタブへ送る
    openConversation.mock.calls[1][0].send('次のタブ')
    expect(send).toHaveBeenLastCalledWith('ses_b', '次のタブ')
  })

  it('writes a sound that was not speech down as nothing, without a word', async () => {
    talk(vi.fn())
    await settle()
    apiFetch.mockResolvedValue(ok({ text: '' }))
    expect(await openConversation.mock.calls[0][0].transcribe(new Blob(['wav']))).toBe('')
    expect(getSnapshot().error.ses_a).toBeUndefined()
  })

  it('sends nothing once it is closed', async () => {
    const send = vi.fn()
    talk(send)
    await settle()
    const deps = openConversation.mock.calls[0][0]
    hangUp()
    deps.send('遅れて届いた文')
    expect(send).not.toHaveBeenCalled()
  })

  it('closes, and says so, when another screen has opened the conversation', async () => {
    talk(vi.fn())
    await settle()
    apiFetch.mockResolvedValue({ ok: false, status: 409, json: async () => ({ detail: { code: 'voice_conversation_elsewhere' } }) })
    expect(await openConversation.mock.calls[0][0].transcribe(new Blob(['wav']))).toBe('')
    expect(getSnapshot().on.ses_a).toBeUndefined()
    expect(getSnapshot().error.ses_a).toBeTruthy()
  })

  it('closes once both the voice and the microphone are off: the microphone, the conversation, and the voice', async () => {
    talk(vi.fn())
    await settle()
    const handle = await openConversation.mock.results[0].value
    apiFetch.mockClear()
    hangUp()
    await settle()
    expect(handle.close).toHaveBeenCalled()
    expect(calls('DELETE', '/voice/conversation')).toHaveLength(1)
    expect(mic.stopped).toBe(1)
    expect(getSnapshot().on.ses_a).toBeUndefined()
    expect(getSnapshot().phase.ses_a).toBeUndefined()
  })

  it('only turns the voice on and off for an agent that does not listen', async () => {
    setVoiceListen('ses_a', false)
    toggleVoice('ses_a', vi.fn())
    await settle()
    expect(getSnapshot().on.ses_a).toBe(true)
    expect(openConversation).not.toHaveBeenCalled()
    expect(calls('POST', '/voice/conversation')).toHaveLength(0)
    toggleVoice('ses_a', vi.fn())
    expect(getSnapshot().on.ses_a).toBeUndefined()
  })

  it('says why when the microphone is refused, and keeps the voice on', async () => {
    mic.refuse = 'NotAllowedError'
    talk(vi.fn())
    await settle(); await settle()
    expect(getSnapshot().on.ses_a).toBe(true)
    expect(getSnapshot().phase.ses_a).toBeUndefined()
    expect(getSnapshot().error.ses_a).toContain('Permission denied')
    expect(openConversation).not.toHaveBeenCalled()
  })

  it('mutes the microphone and keeps the voice on; unmuting listens again', async () => {
    talk(vi.fn())
    await settle()
    const handle = await openConversation.mock.results[0].value
    apiFetch.mockClear()
    toggleMic('ses_a', vi.fn())
    await settle()
    expect(handle.close).toHaveBeenCalled()
    expect(mic.stopped).toBe(1)
    expect(calls('DELETE', '/voice/conversation')).toHaveLength(1)
    expect(getSnapshot().on.ses_a).toBe(true)
    expect(getSnapshot().phase.ses_a).toBeUndefined()
    toggleMic('ses_a', vi.fn())
    expect(getSnapshot().phase.ses_a).toBe('starting')
    await settle()
    expect(openConversation).toHaveBeenCalledTimes(2)
    expect(getSnapshot().on.ses_a).toBe(true)
  })

  it('turning the voice off keeps the microphone listening, and the voice comes back on the next press', async () => {
    talk()
    await settle()
    toggleVoice('ses_a', vi.fn())                 // 声だけ止める
    await settle()
    expect(getSnapshot().on.ses_a).toBe(true)
    expect(getSnapshot().quiet.ses_a).toBe(true)
    expect(getSnapshot().phase.ses_a).toBeTruthy()   // マイクは開いたまま
    expect(mic.stopped).toBe(0)
    toggleVoice('ses_a', vi.fn())                 // 声を戻す
    expect(getSnapshot().quiet.ses_a).toBeUndefined()
    expect(openConversation).toHaveBeenCalledTimes(1)
  })

  it('starts with the microphone closed the next time the voice is turned on, once it was closed', async () => {
    talk(vi.fn())
    await settle()
    toggleMic('ses_a', vi.fn())
    toggleVoice('ses_a', vi.fn())                 // off
    toggleVoice('ses_a', vi.fn())                 // on again
    await settle()
    expect(getSnapshot().on.ses_a).toBe(true)
    expect(getSnapshot().phase.ses_a).toBeUndefined()
    expect(openConversation).toHaveBeenCalledTimes(1)
  })

  it('turning the voice off from muted leaves nothing open', async () => {
    talk(vi.fn())
    await settle()
    toggleMic('ses_a', vi.fn())
    toggleVoice('ses_a', vi.fn())
    expect(getSnapshot().on.ses_a).toBeUndefined()
    expect(getSnapshot().phase.ses_a).toBeUndefined()
  })

  it('starts a conversation with only the microphone, without the voice; an agent that does not listen has none', async () => {
    toggleMic('ses_a', vi.fn())
    await settle()
    expect(getSnapshot().on.ses_a).toBe(true)
    expect(getSnapshot().quiet.ses_a).toBe(true)
    expect(openConversation).toHaveBeenCalledTimes(1)
    toggleMic('ses_a', vi.fn())                   // マイクを切ると、 声も無いので会話を終える
    await settle()
    expect(getSnapshot().on.ses_a).toBeUndefined()
    setVoiceListen('ses_a', false)
    toggleMic('ses_a', vi.fn())
    await settle()
    expect(getSnapshot().on.ses_a).toBeUndefined()
    expect(openConversation).toHaveBeenCalledTimes(1)
  })

  it('hands over no turn model when the agent has none', async () => {
    voiceInfo = { ...voiceInfo, turn: false }
    setVoiceTurn('ses_a', false)
    talk(vi.fn())
    await settle()
    expect(openConversation.mock.calls[0][0].turnModelUrl).toBeNull()
  })
})

describe('startCall — the call Siri starts: the voice and the microphone together', () => {
  it('starts a conversation with the voice on and the microphone open', async () => {
    await startCall('ses_a')
    expect(getSnapshot().on.ses_a).toBe(true)
    expect(getSnapshot().quiet.ses_a).toBeFalsy()
    expect(getSnapshot().phase.ses_a).toBe('starting')
    await settle()
    expect(openConversation).toHaveBeenCalledTimes(1)
  })

  it('opens the microphone of a conversation that only plays the voice', async () => {
    toggleVoice('ses_a')
    await settle()
    expect(openConversation).not.toHaveBeenCalled()
    await startCall('ses_a')
    await settle()
    expect(openConversation).toHaveBeenCalledTimes(1)
  })

  it('does nothing for a tab without a voice', async () => {
    voiceInfo = { enabled: false }
    await startCall('ses_a')
    expect(getSnapshot().on.ses_a).toBeFalsy()
  })
})
