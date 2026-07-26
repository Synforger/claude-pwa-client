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

// ---------------------------------------------------------------------------
// identity 終身保持 (= 2026-07-10 「同文バブル 2 個 = 二重送信に見える」 根治)
// ---------------------------------------------------------------------------

describe('reconcileUserMessage — 再配信の二重表示禁止', () => {
  it('確定済 bubble は send_id を持ち続ける (= _confirmAt が捨てない)', () => {
    const cur = [{ id: 'o1', role: 'user', optimistic: true, send_id: 'S1', text: 'ペースト本文' }]
    const next = reconcileUserMessage(cur, 'ペースト本文', 'U1', 'S1')
    expect(next[0].uuid).toBe('U1')
    expect(next[0].send_id).toBe('S1')
    expect(next[0].optimistic).toBeUndefined()
  })

  it('同 send_id の再配信 (uuid 違い/取りこぼし) は append せず backfill のみ', () => {
    // 1 回目: uuid なし event で確定 (= mapping 取りこぼし形)
    let cur = [{ id: 'o1', role: 'user', optimistic: true, send_id: 'S1', text: 'x' }]
    cur = reconcileUserMessage(cur, 'x', null, 'S1')
    expect(cur).toHaveLength(1)
    expect(cur[0].uuid).toBe(null)
    // 2 回目: 同 send_id + uuid 付き再配信 → 新規 append せず uuid backfill
    const next = reconcileUserMessage(cur, 'x', 'U9', 'S1')
    expect(next).toHaveLength(1)
    expect(next[0].uuid).toBe('U9')
    // 3 回目: 完全な replay → no-op
    expect(reconcileUserMessage(next, 'x', 'U9', 'S1')).toBe(next)
  })

  it('identity 全断でも直近の uuid 未確定同文 bubble を採用して append しない (= 3.5 guard)', () => {
    const cur = [
      { id: 'a', role: 'agent', uuid: 'AM1', text: 'reply' },
      { id: 'u1', role: 'user', uuid: null, text: '同じ本文' },  // 対応付け損ねた自送信
    ]
    const next = reconcileUserMessage(cur, '同じ本文', 'U2', null)
    expect(next).toHaveLength(2)
    expect(next[1].uuid).toBe('U2')
  })

  it('意図的な同文連投は append される (= uuid 確定済の同文は guard 対象外)', () => {
    const cur = [{ id: 'u1', role: 'user', uuid: 'U1', text: 'ok' }]
    const next = reconcileUserMessage(cur, 'ok', 'U2', null)
    expect(next).toHaveLength(2)
    expect(next[1].uuid).toBe('U2')
  })

  // --- GET 履歴 replay が楽観バブルを食い潰さない (= 2026-07-26 実機報告の根治) ---

  it('履歴 replay の古い user_message は送信直後の楽観バブルを pop しない (= 自分の送信が消えない)', () => {
    const NOW = 1900000000000
    const ANCIENT = NOW - 24 * 60 * 60 * 1000  // 1 日前 = 履歴 replay 相当
    const cur = [
      { id: 'm1', uuid: 'U-old', role: 'user', text: '前の発話', ts: NOW - 60000 },
      { id: 'm2', uuid: 'A-old', role: 'agent', text: '前の応答', ts: NOW - 59000 },
      { id: 'm3', role: 'user', text: 'いま送った俺のメッセージ', optimistic: true, send_id: 'S-now', ts: NOW },
    ]
    // identity が両方切れた古い event (= GET 履歴が返す uuid 有 / send_id 無の過去発話)
    const next = reconcileUserMessage(cur, '大昔の発話A', 'U-ancient', undefined, ANCIENT)
    // 楽観バブルは無傷で残る
    const mine = next.find(m => m.text === 'いま送った俺のメッセージ')
    expect(mine).toBeTruthy()
    expect(mine.optimistic).toBe(true)
    // 古い発話は食わずに append される (= 表示位置は MessageList の ts ソートが決める)
    expect(next.find(m => m.uuid === 'U-ancient')).toBeTruthy()
  })

  it('同時刻帯の正規 event は従来通り楽観バブルを pop する (= safety net を殺していない)', () => {
    const NOW = 1900000000000
    const cur = [
      { id: 'm3', role: 'user', text: '送った', optimistic: true, ts: NOW },
    ]
    // server / client の時計ズレを想定した数秒前でも pop できる (= 許容差の内側)
    const next = reconcileUserMessage(cur, '送った', 'U-real', undefined, NOW - 3000)
    expect(next).toHaveLength(1)
    expect(next[0].uuid).toBe('U-real')
    expect(next[0].optimistic).toBeFalsy()
  })

  it('ts が無い event / bubble では従来の近似 match を維持する (= 旧 cache 互換)', () => {
    const cur = [{ id: 'm3', role: 'user', text: '送った', optimistic: true }]
    const next = reconcileUserMessage(cur, '送った', 'U-real', undefined, undefined)
    expect(next).toHaveLength(1)
    expect(next[0].uuid).toBe('U-real')
  })
})
