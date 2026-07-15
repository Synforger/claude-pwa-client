// streaming 増分描画の分割純関数 (= 2026-07-15 電力最適化 R1)。
//
// 不変条件:
// 1. chunks + tail を連結すると元テキストと等価 (= 空行境界の情報も失わない)
// 2. コードフェンスの内側では絶対に切らない
// 3. text が append で伸びても、 過去に閉じた chunk の内容は不変 (= memo が効く前提)
import { describe, it, expect } from 'vitest'
import { splitStreamingBlocks } from './MessageRenderer.jsx'

const join = ({ chunks, tail }) => [...chunks, tail].join('\n')

describe('splitStreamingBlocks', () => {
  it('未完の末尾ブロックだけが tail になる', () => {
    const text = 'para one.\n\npara two still going'
    const { chunks, tail } = splitStreamingBlocks(text)
    expect(tail).toBe('para two still going')
    expect(chunks.join('\n')).toContain('para one.')
    expect(join({ chunks, tail })).toBe(text)
  })

  it('コードフェンス内の空行では切らない', () => {
    const text = '```js\nline1\n\nline2\n```\n\nafter fence still going'
    const { chunks, tail } = splitStreamingBlocks(text)
    // フェンス全体が 1 つの確定側に入り、 tail はフェンス後の未完ブロック
    expect(tail).toBe('after fence still going')
    expect(chunks.join('\n')).toContain('line1\n\nline2')
  })

  it('開きっぱなしのフェンスは丸ごと tail 側 (= 確定させない)', () => {
    const text = 'intro.\n\n```py\ncode grows'
    const { chunks, tail } = splitStreamingBlocks(text)
    expect(tail).toBe('```py\ncode grows')
    expect(chunks.join('\n')).toContain('intro.')
  })

  it('append で伸びても既存 chunk の内容は不変 (= memo 安定性)', () => {
    // 長い確定ブロックで chunk を 2 個以上作る
    const blockA = 'A'.repeat(900) + '.'
    const blockB = 'B'.repeat(900) + '.'
    const base = `${blockA}\n\n${blockB}\n\ntail-in-progress`
    const grown = base + ' and more'
    const p1 = splitStreamingBlocks(base)
    const p2 = splitStreamingBlocks(grown)
    expect(p2.chunks).toEqual(p1.chunks)  // 先頭 chunk 列は完全一致
    expect(p2.tail).toBe('tail-in-progress and more')
    expect(join(p2)).toBe(grown)
  })

  it('空文字 / 単一未完ブロックは chunk なし', () => {
    expect(splitStreamingBlocks('')).toEqual({ chunks: [], tail: '' })
    const { chunks, tail } = splitStreamingBlocks('only one growing block')
    expect(chunks).toEqual([])
    expect(tail).toBe('only one growing block')
  })
})
