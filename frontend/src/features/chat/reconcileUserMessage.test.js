import { describe, it, expect } from 'vitest'
import { reconcileUserMessage } from './reconcileUserMessage.js'

// 2026-06-24 server-of-truth 純化後の test 群。 旧 5 段 (= text 完全一致 / 部分一致 / 添付
// 検出 / LOOKBACK_DEDUP) ヒューリスティクスは全廃され、 dedup は uuid 一致のみ + 末尾
// optimistic を pop して新 event で置換 という 1 段に集約された。

const opt = (text, extra = {}) => ({ id: `opt-${text}`, role: 'user', text, optimistic: true, ...extra })
const confirmed = (text, uuid) => ({ id: `c-${uuid}`, role: 'user', text, uuid, optimistic: false })

describe('reconcileUserMessage (server-of-truth)', () => {
  it('returns the same reference for a known uuid (duplicate delivery on replay)', () => {
    const cur = [confirmed('hi', 'u1')]
    expect(reconcileUserMessage(cur, 'hi', 'u1')).toBe(cur)
  })

  it('pops the trailing optimistic user and confirms it with the event (normal send completion)', () => {
    const cur = [opt('hello')]
    const next = reconcileUserMessage(cur, 'hello', 'u1')
    expect(next).toHaveLength(1)
    expect(next[0]).toMatchObject({ role: 'user', text: 'hello', uuid: 'u1' })
    expect(next[0].optimistic).toBeUndefined()
  })

  it('inherits the optimistic id on pop (failBubble relies on findIndex by optimisticUserId)', () => {
    const cur = [opt('hi')]
    const next = reconcileUserMessage(cur, 'hi', 'u1')
    expect(next[0].id).toBe('opt-hi')
  })

  it('pops the optimistic user even with a streaming agent bubble at the tail (sendMessage pushes both at once)', () => {
    const cur = [opt('hello'), { id: 'a-empty', role: 'agent', text: '', streaming: true }]
    const next = reconcileUserMessage(cur, 'hello', 'u1')
    expect(next).toHaveLength(2)
    expect(next[0]).toMatchObject({ role: 'user', text: 'hello', uuid: 'u1' })
    expect(next[1]).toMatchObject({ role: 'agent', streaming: true })
  })

  it('pops even when event text differs from optimistic text and overwrites with the event text (claude-side prompt rewriting etc.)', () => {
    const cur = [opt('hello')]
    const next = reconcileUserMessage(cur, 'hello (auto-augmented)', 'u1')
    expect(next).toHaveLength(1)
    expect(next[0].text).toBe('hello (auto-augmented)')
    expect(next[0].uuid).toBe('u1')
  })

  it('an optimistic with attachments keeps its original text and never shows the attachment marker in the UI', () => {
    const cur = [opt('画像送るね', { fileNames: ['a.png'] })]
    const next = reconcileUserMessage(cur, '画像送るね [添付ファイル: /tmp/x.png]', 'u3')
    expect(next).toHaveLength(1)
    expect(next[0].text).toBe('画像送るね')
    expect(next[0].uuid).toBe('u3')
    expect(next[0].fileNames).toEqual(['a.png'])
  })

  it('plainly appends the event when no optimistic exists (replay / proactive)', () => {
    const cur = []
    const next = reconcileUserMessage(cur, 'reloaded prompt', 'u2')
    expect(next).toHaveLength(1)
    expect(next[0]).toMatchObject({ role: 'user', text: 'reloaded prompt', uuid: 'u2' })
  })

  it('appends a new event when the tail is a confirmed user with no optimistic (consecutive user messages)', () => {
    const cur = [confirmed('older', 'u1')]
    const next = reconcileUserMessage(cur, 'newer', 'u2')
    expect(next).toHaveLength(2)
    expect(next[1]).toMatchObject({ text: 'newer', uuid: 'u2' })
  })

  it('appends a same-text different-uuid event from a fork lineage correctly (keeps the 2026-06-23 regression fix)', () => {
    const cur = [
      confirmed('やり直して', 'u-fork-1'),
      { id: 'a1', role: 'agent', text: '了解', uuid: 'a1' },
      confirmed('やり直して', 'u-fork-2'),
      { id: 'a2', role: 'agent', text: '再実行します', uuid: 'a2' },
    ]
    const next = reconcileUserMessage(cur, 'やり直して', 'u-fork-3')
    expect(next).toHaveLength(5)
    expect(next[4]).toMatchObject({ role: 'user', text: 'やり直して', uuid: 'u-fork-3' })
  })

  it('appends events without an eventUuid (missing uuids are blocked from persisting by the useChatStorage filter)', () => {
    const cur = [confirmed('older', 'u1')]
    const next = reconcileUserMessage(cur, 'brand new text', undefined)
    expect(next).toHaveLength(2)
    expect(next[1]).toMatchObject({ role: 'user', text: 'brand new text', uuid: null })
  })

  it('with two optimistics in flight, one SSE event pops the nearest-to-tail one and leaves the other optimistic', () => {
    const cur = [opt('一個目'), opt('二個目')]
    const next = reconcileUserMessage(cur, '二個目', 'u2')
    expect(next).toHaveLength(2)
    expect(next[0].optimistic).toBe(true)
    expect(next[1]).toMatchObject({ text: '二個目', uuid: 'u2' })
    expect(next[1].optimistic).toBeUndefined()
  })

  it('no structural duplication: a ghost (confirmed with uuid) plus a same-text different-uuid event just coexist via append (the duplicate-display root cause is cured by the useChatStorage filter that prevents ghosts)', () => {
    // 旧 bug: 過去に uuid なしで持続化された optimistic が ghost として load → 同 text 別
    // uuid の SSE event が step 3 (exact text match) で 1 件確定化 + step 5 で新規 append =
    // 重複。 新設計では ghost を作らない (useChatStorage filter で uuid 必須) ので、 ここに
    // 来た時点で確定済 user は append される、 重複は構造的に起こらない。
    const cur = [confirmed('hello', 'u-old')]
    const next = reconcileUserMessage(cur, 'hello', 'u-new')
    expect(next).toHaveLength(2)
    expect(next[1]).toMatchObject({ text: 'hello', uuid: 'u-new' })
  })
})

describe('reconcileUserMessage (send_id path, identity introduced 2026-07-03)', () => {
  const optWithSendId = (text, send_id) => ({
    id: `opt-${text}`, role: 'user', text, optimistic: true, send_id,
  })

  it('strictly pops the optimistic matching eventSendId even when it is not at the tail (kills mis-pairing under rapid sends)', () => {
    // 連投で楽観 bubble が 2 個並んだ状態で、 先に送った側の SSE event (= send_id=s1) が
    // 到着すると、 fallback の「近傍最後の optimistic pop」 では末尾 (= s2) を誤って
    // pop してしまう。 send_id 一致経路が第 2 優先で走ることで対応付けが決定的になる。
    const cur = [optWithSendId('一個目', 's1'), optWithSendId('二個目', 's2')]
    const next = reconcileUserMessage(cur, '一個目', 'u1', 's1')
    expect(next).toHaveLength(2)
    // 一個目 (= s1) が対応付け先として厳密 pop され、 確定 bubble に置換される。 send_id は
    // uuid が付いた確定後は識別に不要なので confirmed 側には含めない (= persist 汚染防止)。
    expect(next[0]).toMatchObject({ role: 'user', text: '一個目', uuid: 'u1' })
    expect(next[0].optimistic).toBeUndefined()
    // 二個目 (= s2) は fallback (= 末尾近傍 pop) が起きていない証拠として optimistic のまま残る。
    expect(next[1]).toMatchObject({ text: '二個目', send_id: 's2', optimistic: true })
  })

  it('falls back to proximity matching when no optimistic carries the eventSendId (safety net for backend restarts / TTL expiry)', () => {
    const cur = [opt('hello')]
    const next = reconcileUserMessage(cur, 'hello', 'u1', 's-unknown')
    expect(next).toHaveLength(1)
    expect(next[0]).toMatchObject({ role: 'user', text: 'hello', uuid: 'u1' })
    expect(next[0].optimistic).toBeUndefined()
  })

  it('does not fall back when eventSendId matches an existing confirmed message; only the matching optimistic is targeted', () => {
    // send_id は client 発行 identity で、 confirmed には焼かれていない前提。 万一 send_id を
    // 焼いた confirmed が居ても pop 対象外 (optimistic フラグでガード)、 fallback で append される。
    const cur = [{ id: 'c1', role: 'user', text: 'x', uuid: 'u0', send_id: 's1', optimistic: false }]
    const next = reconcileUserMessage(cur, 'x', 'u1', 's1')
    expect(next).toHaveLength(2)
    expect(next[1]).toMatchObject({ role: 'user', text: 'x', uuid: 'u1' })
  })

  it('an exact eventUuid match wins over the send_id path and no-ops (duplicate delivery on replay)', () => {
    const cur = [{ id: 'c1', role: 'user', text: 'x', uuid: 'u1', optimistic: false }]
    expect(reconcileUserMessage(cur, 'x', 'u1', 's1')).toBe(cur)
  })
})
