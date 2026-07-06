// @vitest-environment jsdom
//
// MessageItem の render smoke test (= 2026-07-05 導入)。
//
// 背景: #77 が tool loop 内で shadow された `t` を翻訳関数として呼び、 tool 結果付き
// message の描画が全て TypeError → ErrorBoundary 全画面になった。 当時の 115 test は
// 全て pure logic 単体で、 「component を実際に render する」 検査がゼロだったため
// すり抜けた。 本 file は主要 message 形状を実 render して「描画即死」 級を CI で塞ぐ。
//
// 方針: 表示内容の細かい assert はしない (= 文言変更で壊れる脆い test にしない)。
// 「throw せず render できる + 代表要素が存在する」 の 2 点だけ見る。
import { describe, it, expect, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import MessageItem from './MessageItem.jsx'

afterEach(cleanup)

const noop = () => {}
const baseProps = {
  onOpenFile: noop,
  onAnswer: noop,
  apiKeySource: null,
  activeSubagentTool: null,
  onOpenSubagents: noop,
  onFork: null,
}

describe('MessageItem render smoke', () => {
  it('user message renders', () => {
    const { container } = render(
      <MessageItem {...baseProps} msg={{ id: 'u1', role: 'user', text: 'こんにちは' }} />,
    )
    expect(container.textContent).toContain('こんにちは')
  })

  it('agent message with text renders', () => {
    const { container } = render(
      <MessageItem {...baseProps} msg={{ id: 'a1', role: 'agent', text: '応答です' }} />,
    )
    expect(container.textContent).toContain('応答です')
  })

  it('empty streaming agent renders the thinking placeholder', () => {
    const { container } = render(
      <MessageItem
        {...baseProps}
        msg={{ id: 'a2', role: 'agent', streaming: true, text: '', tools: [] }}
      />,
    )
    expect(container.querySelector('.bubble.dim')).toBeTruthy()
  })

  it('tool with a text result renders (= #79 の crash 再現形状)', () => {
    // tool loop 内の翻訳呼び出し (tool.chars) を必ず踏む形状: result.content が
    // 非空 text + diff なし → showResult=true → 文字数 meta が描画される。
    const { container } = render(
      <MessageItem
        {...baseProps}
        msg={{
          id: 'a3',
          role: 'agent',
          text: '完了しました',
          tools: [{
            id: 't1',
            name: 'Bash',
            label: 'ls -la',
            shortLabel: 'ls',
            result: { content: 'total 42\ndrwxr-xr-x  7 user staff', is_error: false },
          }],
        }}
      />,
    )
    expect(container.querySelector('.tool-block')).toBeTruthy()
    expect(container.querySelector('.tool-meta')).toBeTruthy()
  })

  it('tool with an error result renders', () => {
    const { container } = render(
      <MessageItem
        {...baseProps}
        msg={{
          id: 'a4',
          role: 'agent',
          text: '',
          tools: [{
            id: 't2',
            name: 'Bash',
            label: 'false',
            result: { content: 'exit 1', is_error: true },
          }],
        }}
      />,
    )
    expect(container.querySelector('.tool-block.is-error')).toBeTruthy()
  })

  it('optimistic user with attachments renders', () => {
    const { container } = render(
      <MessageItem
        {...baseProps}
        msg={{
          id: 'u2',
          role: 'user',
          text: '画像を送ります',
          optimistic: true,
          fileNames: ['a.png'],
        }}
      />,
    )
    expect(container.textContent).toContain('画像を送ります')
  })
})
