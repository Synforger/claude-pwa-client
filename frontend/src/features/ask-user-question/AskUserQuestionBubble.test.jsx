// @vitest-environment jsdom
//
// AskUserQuestion の chat log 表示 (= 2026-07-06 統合後の非対話ログ形) の契約 test。
// 回答 UI は prompt detector banner に一本化したので、 この component は
// 「未回答 = 折りたたみの回答待ちログ / 回答済 = 折りたたみの回答ログ」 のみを描画し、
// button / input 等の対話要素を一切持たないことを固定する。
import { describe, it, expect, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import AskUserQuestionBubble from './AskUserQuestionBubble.jsx'

afterEach(cleanup)

const question = {
  header: 'Auth',
  question: 'Which auth method should we use?',
  multiSelect: false,
  options: [
    { label: 'OAuth', description: 'redirect flow' },
    { label: 'API key', description: 'static secret' },
  ],
}

describe('AskUserQuestionBubble (log-only)', () => {
  it('unanswered renders a collapsed waiting log with no interactive elements', () => {
    const { container } = render(
      <AskUserQuestionBubble askUserQuestion={{
        tool_use_id: 't1', questions: [question], answered: false, selectedAnswer: null,
      }} />,
    )
    const details = container.querySelector('details.ask-question.waiting')
    expect(details).toBeTruthy()
    expect(details.open).toBe(false)
    // 対話要素ゼロ (= 回答経路は banner / チャット入力欄)
    expect(container.querySelector('button')).toBeNull()
    expect(container.querySelector('input')).toBeNull()
    // 展開すれば選択肢 + description が読める
    expect(container.textContent).toContain('OAuth')
    expect(container.textContent).toContain('redirect flow')
  })

  it('answered renders the answered log with the selected answer', () => {
    const { container } = render(
      <AskUserQuestionBubble askUserQuestion={{
        tool_use_id: 't1', questions: [question], answered: true, selectedAnswer: 'OAuth',
      }} />,
    )
    expect(container.querySelector('details.ask-question.answered')).toBeTruthy()
    expect(container.querySelector('button')).toBeNull()
    expect(container.textContent).toContain('OAuth')
  })

  it('returns null when there is no question payload', () => {
    const { container } = render(
      <AskUserQuestionBubble askUserQuestion={{ tool_use_id: 't1', questions: [], answered: false }} />,
    )
    expect(container.firstChild).toBeNull()
  })
})
