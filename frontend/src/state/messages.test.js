// state/messages.js (= 真値 message store) の契約 test。
import { describe, it, expect } from 'vitest'
import {
  getMessagesFor,
  appendMessage,
  setMessagesFor,
} from './messages.js'

const agent = (uuid, text = 'x') => ({ role: 'agent', uuid, text, tools: [] })

describe('state/messages — appendMessage', () => {
  it('uuid なし (= optimistic / 非 persistable) は reject される', () => {
    appendMessage('m1', { role: 'user', text: 'optimistic' })
    expect(getMessagesFor('m1')).toHaveLength(0)
  })

  it('同 (uuid, role) の重複 append は no-op (= reconnect replay 安全)', () => {
    appendMessage('m2', agent('AM1'))
    appendMessage('m2', agent('AM1', '別内容'))
    expect(getMessagesFor('m2')).toHaveLength(1)
    expect(getMessagesFor('m2')[0].text).toBe('x')
  })

  it('上限到達で先頭を捨てて末尾に積む (= 総数 200 維持)', () => {
    for (let i = 0; i < 201; i++) appendMessage('m3', agent(`u${i}`, String(i)))
    const arr = getMessagesFor('m3')
    expect(arr).toHaveLength(200)
    expect(arr[0].uuid).toBe('u1')
    expect(arr.at(-1).uuid).toBe('u200')
  })

  it('未存在 sid の取得は空配列', () => {
    expect(getMessagesFor('ghost')).toEqual([])
  })
})

describe('state/messages — setMessagesFor', () => {
  it('丸ごと置換 + 非 persistable を filter する (= 復元経路の防御)', () => {
    setMessagesFor('m4', [
      agent('AM1'),
      { role: 'user', text: 'no-uuid' },
      { role: 'system', kind: 'task' },  // uuid undefined (= J-16 形)
    ])
    const arr = getMessagesFor('m4')
    expect(arr).toHaveLength(1)
    expect(arr[0].uuid).toBe('AM1')
  })
})
