// state/ephemeral.js (= 描画専用 singleton) の契約 test。
import { describe, it, expect } from 'vitest'
import {
  getSnapshot,
  setAttachments,
  clearAttachments,
  setLoading,
  clearLoading,
  setApiKeySource,
  getStreamBuffer,
  bumpStreamBuffer,
  resetStreamBuffer,
  setSendFailedText,
  setStopUnavailableSid,
  bumpAttachmentPicker,
  bumpReconnectKey,
} from './ephemeral.js'

describe('state/ephemeral — sid 別 dict 更新', () => {
  it('attachments は sid 単位で set / clear できる', () => {
    setAttachments('s1', [{ name: 'a.png' }])
    expect(getSnapshot().attachments.s1).toHaveLength(1)
    clearAttachments('s1')
    expect('s1' in getSnapshot().attachments).toBe(false)
    // 存在しない sid の clear は no-op (= 参照不変)
    const snap = getSnapshot()
    clearAttachments('nope')
    expect(getSnapshot()).toBe(snap)
  })

  it('loading は同値 set で bailout、 clearLoading で全消し', () => {
    setLoading('s1', true)
    const snap = getSnapshot()
    setLoading('s1', true)
    expect(getSnapshot()).toBe(snap)
    setLoading('s2', false)
    clearLoading()
    expect(Object.keys(getSnapshot().loading)).toHaveLength(0)
    const empty = getSnapshot()
    clearLoading()
    expect(getSnapshot()).toBe(empty)
  })

  it('apiKeySource は sid 別に積める', () => {
    setApiKeySource('s1', 'apiKey')
    expect(getSnapshot().apiKeySource.s1).toBe('apiKey')
  })
})

describe('state/ephemeral — stream buffer (= mutate-in-place + bump 通知)', () => {
  it('getStreamBuffer は lazy 初期化して同一 object を返す', () => {
    const buf = getStreamBuffer('sb1')
    expect(buf.dirty).toBe(false)
    expect(getStreamBuffer('sb1')).toBe(buf)
  })

  it('bumpStreamBuffer は中身を保って reference だけ更新する', () => {
    const buf = getStreamBuffer('sb2')
    buf.text = 'streaming...'
    buf.dirty = true
    bumpStreamBuffer('sb2')
    const after = getSnapshot().streamBuffers.sb2
    expect(after).not.toBe(buf)
    expect(after.text).toBe('streaming...')
    expect(after.dirty).toBe(true)
  })

  it('resetStreamBuffer で初期形に戻る', () => {
    getStreamBuffer('sb3').text = 'x'
    resetStreamBuffer('sb3')
    expect(getSnapshot().streamBuffers.sb3.text).toBe('')
    expect(getSnapshot().streamBuffers.sb3.dirty).toBe(false)
  })
})

describe('state/ephemeral — one-shot signal 群', () => {
  it('sendFailedText / stopUnavailableSid は同値 set で bailout する', () => {
    setSendFailedText('failed body')
    const snap = getSnapshot()
    setSendFailedText('failed body')
    expect(getSnapshot()).toBe(snap)
    setSendFailedText(null)
    setStopUnavailableSid('s1')
    setStopUnavailableSid(null)
    expect(getSnapshot().stopUnavailableSid).toBe(null)
  })

  it('bump 系 counter は単調増加する', () => {
    const a = getSnapshot().attachmentPickerBump
    bumpAttachmentPicker()
    expect(getSnapshot().attachmentPickerBump).toBe(a + 1)
    const r = getSnapshot().reconnectKey
    bumpReconnectKey()
    expect(getSnapshot().reconnectKey).toBe(r + 1)
  })
})
