// @vitest-environment jsdom
//
// 折りたたむ system のカード (AttachmentCard / HookErrorCard / SystemNoteCard) の 1 行は、 道具の行と
// 封筒の行 (EnvelopeLine) と同じく、 行頭に開閉の印 (.tool-marker の ▸) を持つ。 開いた時の ▾ は CSS が出す。
import { describe, it, expect, afterEach } from 'vitest'
import { render, cleanup } from '@testing-library/react'
import { AttachmentCard, HookErrorCard, SystemNoteCard } from '../../../src/features/chat/SystemMessages.jsx'

afterEach(cleanup)

describe('folding system cards', () => {
  it.each([
    ['AttachmentCard', <AttachmentCard msg={{ subtype: 'auto_mode', attachment: {} }} />, 'attachment-card'],
    ['HookErrorCard', <HookErrorCard msg={{ hookName: 'pre-commit', exitCode: 1 }} />, 'hook-error-card'],
    ['SystemNoteCard', <SystemNoteCard msg={{ subtype: 'local_command', content: '/model' }} />, 'system-note-card'],
  ])('%s starts its summary line with the ▸ mark, before the words', (_name, card, cardClass) => {
    const { container } = render(card)
    const summary = container.querySelector(`.${cardClass} details > summary`)
    const marker = summary.querySelector('.tool-marker')
    expect(marker.textContent).toBe('▸')
    expect(summary.textContent.startsWith('▸')).toBe(true)
    expect(container.querySelector(`.${cardClass} details`).hasAttribute('open')).toBe(false)
  })
})
