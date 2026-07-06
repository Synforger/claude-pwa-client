// diffLines / compactDiff (= file preview の行 diff) の契約 test。
import { describe, it, expect } from 'vitest'
import { diffLines, compactDiff } from './diff.js'

describe('diffLines', () => {
  it('追加 / 削除 / 共通行を LCS で分類する', () => {
    const ops = diffLines('a\nb\nc', 'a\nx\nc')
    expect(ops).toEqual([
      { type: 'ctx', text: 'a' },
      { type: 'add', text: 'x' },
      { type: 'del', text: 'b' },
      { type: 'ctx', text: 'c' },
    ])
  })

  it('末尾改行の有無で余分な空行 diff を出さない', () => {
    expect(diffLines('a\n', 'a\n')).toEqual([{ type: 'ctx', text: 'a' }])
  })

  it('null / 空文字は空配列や全追加として扱う', () => {
    expect(diffLines(null, null)).toEqual([])
    expect(diffLines(null, 'a\nb')).toEqual([
      { type: 'add', text: 'a' },
      { type: 'add', text: 'b' },
    ])
  })

  it('LCS セル上限超過は全削除+全追加へ手抜きする (= フリーズ防止)', () => {
    const big = Array.from({ length: 1500 }, (_, i) => `line${i}`).join('\n')
    const big2 = Array.from({ length: 1500 }, (_, i) => `LINE${i}`).join('\n')
    const ops = diffLines(big, big2)
    expect(ops.filter(o => o.type === 'ctx')).toHaveLength(0)
    expect(ops.filter(o => o.type === 'del')).toHaveLength(1500)
    expect(ops.filter(o => o.type === 'add')).toHaveLength(1500)
  })
})

describe('compactDiff', () => {
  it('差分より contextLines 以上手前の ctx を gap に畳む (= 末尾側は marker なしで落ちる)', () => {
    const ops = [
      ...Array.from({ length: 10 }, (_, i) => ({ type: 'ctx', text: `c${i}` })),
      { type: 'add', text: 'NEW' },
      ...Array.from({ length: 10 }, (_, i) => ({ type: 'ctx', text: `d${i}` })),
    ]
    const out = compactDiff(ops, 2)
    const gaps = out.filter(o => o.type === 'gap')
    expect(gaps).toHaveLength(1)
    expect(gaps[0].skippedLines).toBe(8)
    expect(out.filter(o => o.type === 'add')).toHaveLength(1)
    // 末尾側の遠い ctx は出力されない (= gap marker も出さない現仕様の固定)
    expect(out.at(-1).text).toBe('d1')
  })

  it('空入力はそのまま返す', () => {
    expect(compactDiff([])).toEqual([])
  })
})
