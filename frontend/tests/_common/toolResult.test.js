import { describe, it, expect } from 'vitest'
import { stripToolResultImages, stripMessageToolResultImages } from '../../src/_common/toolResult.js'
import { formatToolResultContent } from '../../src/_common/format.js'
import { toStorableForm } from '../../src/features/chat/useChatStorage.js'

// tool_result の画像本体は表示に使われない (= UI は「画像」 プレースホルダ 1 語に畳む) のに、
// ライブ SSE 経由で受けた分は state / localStorage に base64 ごと載っていた。 実測では
// 1 件 1.1MB の tool_result が 44 本 (計 19.8MB) 積まれ、 保存前の structured clone だけで
// main thread が 150-500ms 止まっていた。 ここはその縮小の契約テスト。

const imageBlock = () => ({
  type: 'image',
  source: { type: 'base64', media_type: 'image/png', data: 'A'.repeat(4096) },
})

describe('stripToolResultImages', () => {
  it('string content はそのまま返す (= 同一参照)', () => {
    const content = 'plain text result'
    expect(stripToolResultImages(content)).toBe(content)
  })

  it('null / undefined はそのまま返す', () => {
    expect(stripToolResultImages(null)).toBe(null)
    expect(stripToolResultImages(undefined)).toBe(undefined)
  })

  it('画像を含まない block list は同一参照を返す (= 上位の参照比較を壊さない)', () => {
    const content = [{ type: 'text', text: 'hello' }]
    expect(stripToolResultImages(content)).toBe(content)
  })

  it('既に畳み済みの画像 (= type だけ) は同一参照を返す', () => {
    const content = [{ type: 'image' }]
    expect(stripToolResultImages(content)).toBe(content)
  })

  it('画像本体を落とし type だけ残す', () => {
    const content = [imageBlock()]
    const out = stripToolResultImages(content)
    expect(out).not.toBe(content)
    expect(out).toEqual([{ type: 'image' }])
    // 元の配列は破壊しない
    expect(content[0].source).toBeTruthy()
  })

  it('text / 未知ブロックは無傷のまま画像だけ落とす', () => {
    const text = { type: 'text', text: 'before' }
    const unknown = { type: 'tool_reference', tool_name: 'Read' }
    const out = stripToolResultImages([text, imageBlock(), unknown])
    expect(out[0]).toBe(text)
    expect(out[1]).toEqual({ type: 'image' })
    expect(out[2]).toBe(unknown)
  })

  it('縮小しても表示結果は 1 文字も変わらない', () => {
    const content = [{ type: 'text', text: 'output' }, imageBlock()]
    const before = formatToolResultContent(content)
    const after = formatToolResultContent(stripToolResultImages(content))
    expect(after).toBe(before)
  })
})

describe('stripMessageToolResultImages', () => {
  it('tools が無い message は同一参照を返す', () => {
    const msg = { id: 'm1', role: 'agent', text: 'hi' }
    expect(stripMessageToolResultImages(msg)).toBe(msg)
  })

  it('画像を持たない tools は同一参照を返す', () => {
    const msg = { id: 'm1', role: 'agent', tools: [{ id: 't1', result: { content: 'ok' } }] }
    expect(stripMessageToolResultImages(msg)).toBe(msg)
  })

  it('result がまだ無い tool (= 実行中) を壊さない', () => {
    const msg = { id: 'm1', role: 'agent', tools: [{ id: 't1', name: 'Bash' }] }
    expect(stripMessageToolResultImages(msg)).toBe(msg)
  })

  it('画像を持つ tool だけ差し替え、 他の tool は同一参照のまま残す', () => {
    const plain = { id: 't1', result: { content: 'ok' } }
    const heavy = { id: 't2', result: { content: [imageBlock()], is_error: false } }
    const msg = { id: 'm1', role: 'agent', tools: [plain, heavy] }
    const out = stripMessageToolResultImages(msg)
    expect(out).not.toBe(msg)
    expect(out.tools[0]).toBe(plain)
    expect(out.tools[1].result.content).toEqual([{ type: 'image' }])
    // result の他 field は保つ
    expect(out.tools[1].result.is_error).toBe(false)
  })
})

describe('toStorableForm', () => {
  it('保存形から画像本体が落ちる (= 既に state に載っている分の救済経路)', () => {
    const msg = {
      id: 'm1',
      role: 'agent',
      tools: [{ id: 't1', result: { content: [{ type: 'text', text: 'out' }, imageBlock()] } }],
    }
    const stored = toStorableForm(msg)
    expect(stored.tools[0].result.content).toEqual([
      { type: 'text', text: 'out' },
      { type: 'image' },
    ])
    expect(JSON.stringify(stored).length).toBeLessThan(500)
  })

  it('streaming が立っていても保存形は作る (= flag だけ落とす)', () => {
    const stored = toStorableForm({
      id: 'm1',
      role: 'agent',
      streaming: true,
      tools: [{ id: 't1', result: { content: [imageBlock()] } }],
    })
    expect(stored).not.toBeNull()
    expect('streaming' in stored).toBe(false)
    // 画像本体を落とす経路は streaming でも同じく通る
    expect(stored.tools[0].result.content).toEqual([{ type: 'image' }])
  })
})

// A tool result is cut to a length the caller chooses, the way the backend cuts the history GET
// (`_shrink_tool_results` in backend/jsonl/routes.py).
import { capToolResultText, capMessageToolResults } from '../../src/_common/toolResult.js'

describe('capToolResultText', () => {
  it('a string within the limit comes back as it is, without a length before the cut', () => {
    const content = 'short'
    expect(capToolResultText(content, 10)).toEqual({ content: 'short', fullChars: null })
    expect(capToolResultText(content, 10).content).toBe(content)
  })

  it('a longer string is cut to the limit and its length is returned', () => {
    expect(capToolResultText('abcdefghij', 4)).toEqual({ content: 'abcd', fullChars: 10 })
  })

  it('text blocks share the budget in order; a block past the budget is dropped, others are kept', () => {
    const image = { type: 'image' }
    const out = capToolResultText([{ type: 'text', text: 'aaaa' }, image, { type: 'text', text: 'bbbb' }, { type: 'text', text: 'cc' }], 6)
    expect(out.content).toEqual([{ type: 'text', text: 'aaaa' }, image, { type: 'text', text: 'bb' }])
    expect(out.content[1]).toBe(image)
    expect(out.fullChars).toBe(10)
  })

  it('a block list within the limit keeps its reference', () => {
    const content = [{ type: 'text', text: 'abc' }]
    const out = capToolResultText(content, 10)
    expect(out.content).toBe(content)
    expect(out.fullChars).toBeNull()
  })

  it('plain strips ANSI codes first, so the limit counts what is drawn', () => {
    const colored = `\x1b[31m${'r'.repeat(6)}\x1b[0m`
    expect(capToolResultText(colored, 4, { plain: true })).toEqual({ content: 'rrrr', fullChars: 6 })
    expect(capToolResultText(colored, 4)).toEqual({ content: colored.slice(0, 4), fullChars: colored.length })
  })

  it('what is not a string or a list (null, undefined) is returned as it is', () => {
    expect(capToolResultText(null, 5)).toEqual({ content: null, fullChars: null })
    expect(capToolResultText(undefined, 5)).toEqual({ content: undefined, fullChars: null })
  })
})

describe('capMessageToolResults', () => {
  const message = (content, extra = {}) => ({ id: 'a1', role: 'agent', tools: [{ id: 't1', result: { content, is_error: false, ...extra } }] })

  it('a result longer than the limit is cut and its length goes to full_chars', () => {
    const out = capMessageToolResults(message('x'.repeat(50)), 10)
    expect(out.tools[0].result.content).toBe('x'.repeat(10))
    expect(out.tools[0].result.full_chars).toBe(50)
    expect(out.tools[0].result.is_error).toBe(false)
  })

  it('a length the result already carries is kept when it is the larger', () => {
    expect(capMessageToolResults(message('x'.repeat(50), { full_chars: 9000 }), 10).tools[0].result.full_chars).toBe(9000)
  })

  it('the same message comes back when nothing is cut, and a message without tools is not touched', () => {
    const short = message('abc')
    expect(capMessageToolResults(short, 10)).toBe(short)
    const plain = { id: 'a2', role: 'agent', text: 'hi' }
    expect(capMessageToolResults(plain, 10)).toBe(plain)
    expect(capMessageToolResults(null, 10)).toBeNull()
  })
})
