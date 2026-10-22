// @vitest-environment jsdom
//
// 📋 の頭には、 そのタブのトップページへのリンクが固定で出る (= メモの本文とは別の行)。 ページが無いタブでは出ない。
// 押すと path の開き方 (= openPath) で開き、 書く最中には出ない。
import { it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, cleanup, fireEvent, screen, waitFor, act } from '@testing-library/react'
import NoteModal from '../../../src/features/notes/NoteModal.jsx'
import { setOverlay } from '../../../src/state/ui.js'
import * as sessions from '../../../src/state/sessions.js'

const openPath = vi.hoisted(() => vi.fn())
vi.mock('../../../src/features/file-preview/openPath.js', () => ({ openPath }))

const SID = 'ses_note'

function answerWith(note) {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(note), { status: 200 }))
}

beforeEach(() => {
  vi.spyOn(sessions, 'getSnapshot').mockReturnValue({ activeId: SID, sessions: [] })
})

afterEach(() => {
  act(() => setOverlay('notes', false))
  cleanup()
  vi.restoreAllMocks()
  openPath.mockReset()
})

it('shows the link to the tab\'s top page above the memo, and opens it by the path', async () => {
  answerWith({ path: '/a/pages/x/memo.md', content: '# メモ', page: '/a/pages/x/index.html' })
  render(<NoteModal />)
  const link = await screen.findByTestId('notes-page-link')
  expect(link.textContent).toContain('Page')
  expect(screen.getByTestId('notes-body').firstElementChild).toBe(link)
  fireEvent.click(link)
  expect(openPath).toHaveBeenCalledTimes(1)
  expect(openPath.mock.calls[0][0]).toBe('/a/pages/x/index.html')
})

it('keeps the link when the memo is empty, because the link is not part of the memo', async () => {
  answerWith({ path: '/a/pages/x/memo.md', content: '', page: '/a/pages/x/index.html' })
  render(<NoteModal />)
  await screen.findByTestId('notes-page-link')
  expect(screen.queryByTestId('notes-reset')).toBeNull()
})

it('shows no link for a tab without a top page', async () => {
  answerWith({ path: '/a/pages/x/memo.md', content: '# メモ', page: null })
  render(<NoteModal />)
  await screen.findByTestId('notes-text')
  expect(screen.queryByTestId('notes-page-link')).toBeNull()
})

it('hides the link while the memo is being written', async () => {
  answerWith({ path: '/a/pages/x/memo.md', content: '# メモ', page: '/a/pages/x/index.html' })
  render(<NoteModal />)
  await screen.findByTestId('notes-page-link')
  fireEvent.click(screen.getByTestId('notes-edit'))
  await waitFor(() => expect(screen.queryByTestId('notes-page-link')).toBeNull())
})
