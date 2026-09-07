import { describe, it, expect } from 'vitest'
import {
  isOversizedMessage,
  isCollapsibleMessage,
  previewUpTo,
  COLLAPSE_CHARS,
  PLAIN_FALLBACK_CHARS,
} from './MessageRenderer.jsx'

describe('isOversizedMessage (= markdown を通さない plain 退避)', () => {
  it('正常系の最長クラス (= subagent transcript 相当) は markdown のまま', () => {
    expect(isOversizedMessage('ふつうの回答'.repeat(100))).toBe(false)
    expect(isOversizedMessage('a'.repeat(PLAIN_FALLBACK_CHARS))).toBe(false)
    // 実測の正常系最大 25,916 字 (= 2026-09-08、 jsonl 470 本) は退避させない
    expect(isOversizedMessage('a'.repeat(25_916))).toBe(false)
  })

  it('閾値超えは plain text へ倒す', () => {
    expect(isOversizedMessage('a'.repeat(PLAIN_FALLBACK_CHARS + 1))).toBe(true)
  })

  it('出力 degeneration (= 同一語の数万回反復) を捕まえる', () => {
    // 実際に観測した 224KB の "court" 反復メッセージ相当。
    const degenerate = 'court\n\n'.repeat(32000)
    expect(degenerate.length).toBeGreaterThan(200_000)
    expect(isOversizedMessage(degenerate)).toBe(true)
  })

  it('非文字列と空は false', () => {
    expect(isOversizedMessage('')).toBe(false)
    expect(isOversizedMessage(null)).toBe(false)
    expect(isOversizedMessage(undefined)).toBe(false)
  })
})

describe('isCollapsibleMessage (= markdown のまま畳む)', () => {
  it('日常の長文 (= p99 = 3,613 字) は畳まない', () => {
    expect(isCollapsibleMessage('a'.repeat(3_613))).toBe(false)
    expect(isCollapsibleMessage('a'.repeat(COLLAPSE_CHARS))).toBe(false)
  })

  it('閾値超えは畳む', () => {
    expect(isCollapsibleMessage('a'.repeat(COLLAPSE_CHARS + 1))).toBe(true)
  })

  it('plain 退避の閾値は折りたたみより上 (= 畳む前に plain へ落ちない)', () => {
    expect(COLLAPSE_CHARS).toBeLessThan(PLAIN_FALLBACK_CHARS)
  })

  it('非文字列と空は false', () => {
    expect(isCollapsibleMessage('')).toBe(false)
    expect(isCollapsibleMessage(null)).toBe(false)
  })
})

describe('previewUpTo (= 折りたたみプレビューの切り出し)', () => {
  it('max 以下はそのまま返す', () => {
    expect(previewUpTo('short', 100)).toBe('short')
  })

  it('ブロック境界 (= 空行) まで下げて切る', () => {
    const text = 'first block\n\nsecond block\n\nthird block that overflows'
    const out = previewUpTo(text, 30)
    expect(out).toBe('first block\n\nsecond block')
    expect(out.length).toBeLessThanOrEqual(30)
  })

  it('コードフェンスの内側では切らない', () => {
    const text = 'intro\n\n```js\nconst a = 1\n\nconst b = 2\n```\n\ntail'
    const out = previewUpTo(text, 30)
    // フェンス内の空行を境界に採らないので、 開いたままの ``` を残さない
    const fences = (out.match(/```/g) || []).length
    expect(fences % 2).toBe(0)
  })

  it('境界が取れない時もフェンスは閉じて返す', () => {
    const text = '```js\n' + 'x'.repeat(500) + '\n' + 'y'.repeat(500) + '\n```'
    const out = previewUpTo(text, 520)
    expect((out.match(/```/g) || []).length % 2).toBe(0)
    expect(out.endsWith('```')).toBe(true)
  })

  it('改行を持たない 1 行は文字数で切る', () => {
    const out = previewUpTo('z'.repeat(5000), 2000)
    expect(out.length).toBe(2000)
  })

  it('表の途中で切らない', () => {
    const table = '| a | b |\n| - | - |\n| 1 | 2 |\n| 3 | 4 |'
    const text = 'lead\n\n' + table + '\n\ntail'
    const out = previewUpTo(text, 20)
    expect(out).toBe('lead')
  })
})
