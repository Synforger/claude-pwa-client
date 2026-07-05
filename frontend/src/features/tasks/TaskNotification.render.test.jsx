// @vitest-environment jsdom
//
// TaskNotification の render smoke (= inline 展開導入 2026-07-05)。
// bash / monitor / unknown 型はカード直下 inline 展開、 agent 型は SubagentsModal 経路
// (= overlay set のみ、 body は開かない) の分岐を実 render で確認する。
import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, cleanup, fireEvent } from '@testing-library/react'

vi.mock('../../utils/api.js', () => ({
  apiFetch: vi.fn(() => Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ content: 'raw task output' }),
  })),
}))

import TaskNotification from './TaskNotification.jsx'
import { getSnapshot as getUiSnapshot } from '../../state/ui.js'

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

  it('agent 型: タップは overlay (SubagentsModal) を立てて inline body は開かない', () => {
    const { container, queryByTestId } = render(<TaskNotification msg={agentMsg} />)
    fireEvent.click(container.querySelector('.task-note-head'))
    expect(queryByTestId('task-note-body')).toBeNull()
    expect(getUiSnapshot().overlays.subagents).toBe(true)
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
