// @vitest-environment jsdom
//
// TaskNotification の render smoke (= inline 展開導入 2026-07-05)。
// どの型もタップでカード直下に inline 展開する (= bash / monitor / agent / unknown)。 実 render で確認する。
import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, cleanup, fireEvent } from '@testing-library/react'

vi.mock('../../../src/_common/api.js', () => ({
  apiFetch: vi.fn(() => Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ content: 'raw task output' }),
  })),
}))

import TaskNotification from '../../../src/features/tasks/TaskNotification.jsx'

afterEach(cleanup)

const bashMsg = {
  summary: 'Background command "npm run build" completed (exit code 0)',
  outputFile: '/tmp/out.txt',
  exitCode: 0,
}
const agentMsg = {
  summary: 'Agent "review" finished',
  outputFile: '/tmp/agent.jsonl',
  exitCode: null,
}

describe('TaskNotification render smoke', () => {
  it('bash 型: タップでカード直下に inline body が開閉する', async () => {
    const { container, findByTestId, queryByTestId } = render(<TaskNotification msg={bashMsg} />)
    expect(queryByTestId('task-note-body')).toBeNull()
    fireEvent.click(container.querySelector('.task-note-head'))
    expect(await findByTestId('task-note-body')).toBeTruthy()
    fireEvent.click(container.querySelector('.task-note-head'))
    expect(queryByTestId('task-note-body')).toBeNull()
  })

  it('agent 型: bash 型と同じく、 タップでカード直下に inline body が開く', async () => {
    const { container, findByTestId } = render(<TaskNotification msg={agentMsg} />)
    fireEvent.click(container.querySelector('.task-note-head'))
    expect(await findByTestId('task-note-body')).toBeTruthy()
  })

  it('outputFile なし: ボタン disabled、 タップ不能', () => {
    const { container } = render(
      <TaskNotification msg={{ summary: 'Monitor event: "x"', outputFile: null, exitCode: null }} />,
    )
    expect(container.querySelector('.task-note-head').disabled).toBe(true)
  })

  it('exit code 非 0 は error 表示', () => {
    const { container } = render(
      <TaskNotification msg={{ ...bashMsg, exitCode: 1 }} />,
    )
    expect(container.querySelector('.task-note-card.is-error')).toBeTruthy()
  })
})
