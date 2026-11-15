// @vitest-environment jsdom
//
// 📋 は、 メモを読んだ時の版 (= 応答の ETag) を書く時の `If-Match` で返す。 読んだ後にエージェントがメモを書いていたら
// backend が 409 で断るので、 画面は「開き直してください」 を出し、 書きかけの文を残す。
import { it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, cleanup, fireEvent, screen, waitFor, act } from '@testing-library/react'
import NoteModal from '../../../src/features/notes/NoteModal.jsx'
import { setOverlay } from '../../../src/state/ui.js'
import * as sessions from '../../../src/state/sessions.js'

vi.mock('../../../src/features/file-preview/openPath.js', () => ({ openLinkedPath: vi.fn() }))

const SID = 'ses_note'
const NOTE = { path: '/a/pages/x/memo.md', content: '- 状態: 作業中', page: null }
const CHANGED = { detail: { code: 'note_changed', message: 'メモが変わりました。開き直してください' } }
const CHANGED_TEXT = 'The notes changed. Reopen them and try again.'   // この環境の言語 (= 英語) での文言

function json(body, status, headers = {}) {
  return new Response(JSON.stringify(body), { status, headers })
}

// 読みには今の版 (= 最初は v1、 書きが通ったらその答えの版) を付けて返し、 書きには次に渡された答えを返す。
// 呼ばれた (url, init) を残す。
function backend(...writes) {
  const calls = []
  let version = '"v1"'
  vi.spyOn(globalThis, 'fetch').mockImplementation((url, init = {}) => {
    calls.push({ url: String(url), init })
    if (init.method !== 'PUT') return Promise.resolve(json(NOTE, 200, { ETag: version }))
    const answer = writes.shift()
    if (answer.ok) version = answer.headers.get('ETag')
    return Promise.resolve(answer)
  })
  return calls
}

const puts = calls => calls.filter(c => c.init.method === 'PUT')

async function editAndSave(text) {
  render(<NoteModal />)
  await screen.findByTestId('notes-text')
  fireEvent.click(screen.getByTestId('notes-edit'))
  fireEvent.change(screen.getByTestId('notes-editor'), { target: { value: text } })
  fireEvent.click(screen.getByTestId('notes-save'))
}

beforeEach(() => {
  vi.spyOn(sessions, 'getSnapshot').mockReturnValue({ activeId: SID, sessions: [] })
})

afterEach(() => {
  act(() => setOverlay('notes', false))
  cleanup()
  vi.restoreAllMocks()
})

it('sends the version it read with the save', async () => {
  const calls = backend(json({ path: NOTE.path, content: 'mine' }, 200, { ETag: '"v2"' }))
  await editAndSave('mine')
  await waitFor(() => expect(puts(calls)).toHaveLength(1))
  expect(puts(calls)[0].init.headers['If-Match']).toBe('"v1"')
})

it('keeps what was being written, and says to reopen, when the memo changed since it was read', async () => {
  backend(json(CHANGED, 409))
  await editAndSave('my unsaved text')
  await screen.findByText(CHANGED_TEXT)
  expect(screen.getByTestId('notes-editor').value).toBe('my unsaved text')
})

it('saves the next time with the version the last save answered', async () => {
  const calls = backend(
    json({ path: NOTE.path, content: 'one' }, 200, { ETag: '"v2"' }),
    json({ path: NOTE.path, content: 'two' }, 200, { ETag: '"v3"' }),
  )
  await editAndSave('one')
  await screen.findByTestId('notes-edit')
  fireEvent.click(screen.getByTestId('notes-edit'))
  fireEvent.change(screen.getByTestId('notes-editor'), { target: { value: 'two' } })
  fireEvent.click(screen.getByTestId('notes-save'))
  await waitFor(() => expect(puts(calls)).toHaveLength(2))
  expect(puts(calls).map(c => c.init.headers['If-Match'])).toEqual(['"v1"', '"v2"'])
})

it('shows a save that failed for another reason with its reason, and keeps the text too', async () => {
  backend(json({ detail: { code: 'file_too_large', message: 'big', params: { limit: '1MB' } } }, 413))
  await editAndSave('x')
  await screen.findByText(/保存に失敗しました|Save failed/)
  expect(screen.getByTestId('notes-editor').value).toBe('x')
})
