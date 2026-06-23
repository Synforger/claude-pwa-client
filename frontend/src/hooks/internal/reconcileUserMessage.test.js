import { describe, it, expect } from 'vitest'
import { reconcileUserMessage } from './reconcileUserMessage.js'

// 2026-06-24 server-of-truth 純化後の test 群。 旧 5 段 (= text 完全一致 / 部分一致 / 添付
// 検出 / LOOKBACK_DEDUP) ヒューリスティクスは全廃され、 dedup は uuid 一致のみ + 末尾
// optimistic を pop して新 event で置換 という 1 段に集約された。

const opt = (text, extra = {}) => ({ id: `opt-${text}`, role: 'user', text, optimistic: true, ...extra })
const confirmed = (text, uuid) => ({ id: `c-${uuid}`, role: 'user', text, uuid, optimistic: false })

describe('reconcileUserMessage (server-of-truth)', () => {
  it('既知 uuid なら同一参照を返す (= replay の重複受信)', () => {
    const cur = [confirmed('hi', 'u1')]
    expect(reconcileUserMessage(cur, 'hi', 'u1')).toBe(cur)
  })

  it('末尾の optimistic user を pop して event で確定化 (= 通常の送信完了)', () => {
    const cur = [opt('hello')]
    const next = reconcileUserMessage(cur, 'hello', 'u1')
    expect(next).toHaveLength(1)
    expect(next[0]).toMatchObject({ role: 'user', text: 'hello', uuid: 'u1' })
    expect(next[0].optimistic).toBeUndefined()
  })

  it('pop 時に optimistic の id を継承する (= sendFailed watcher が hit できる前提)', () => {
    const cur = [opt('hi')]
    const next = reconcileUserMessage(cur, 'hi', 'u1')
    expect(next[0].id).toBe('opt-hi')
  })

  it('末尾に streaming agent bubble があっても optimistic user を pop できる (= sendMessage の同時 push 構造)', () => {
    const cur = [opt('hello'), { id: 'a-empty', role: 'agent', text: '', streaming: true }]
    const next = reconcileUserMessage(cur, 'hello', 'u1')
    expect(next).toHaveLength(2)
    expect(next[0]).toMatchObject({ role: 'user', text: 'hello', uuid: 'u1' })
    expect(next[1]).toMatchObject({ role: 'agent', streaming: true })
  })

  it('event text と optimistic text が異なっても pop して event の text で上書き (= claude 側 prompt 加工等)', () => {
    const cur = [opt('hello')]
    const next = reconcileUserMessage(cur, 'hello (auto-augmented)', 'u1')
    expect(next).toHaveLength(1)
    expect(next[0].text).toBe('hello (auto-augmented)')
    expect(next[0].uuid).toBe('u1')
  })

  it('添付付き optimistic は元 text を保持して `[添付ファイル: ...]` を UI に出さない', () => {
    const cur = [opt('画像送るね', { fileNames: ['a.png'] })]
    const next = reconcileUserMessage(cur, '画像送るね [添付ファイル: /tmp/x.png]', 'u3')
    expect(next).toHaveLength(1)
    expect(next[0].text).toBe('画像送るね')
    expect(next[0].uuid).toBe('u3')
    expect(next[0].fileNames).toEqual(['a.png'])
  })

  it('optimistic が無ければ event を単純 append (= replay / proactive)', () => {
    const cur = []
    const next = reconcileUserMessage(cur, 'reloaded prompt', 'u2')
    expect(next).toHaveLength(1)
    expect(next[0]).toMatchObject({ role: 'user', text: 'reloaded prompt', uuid: 'u2' })
  })

  it('末尾が確定 user (= optimistic 無し) の時は新 event を append する (= 連続 user message)', () => {
    const cur = [confirmed('older', 'u1')]
    const next = reconcileUserMessage(cur, 'newer', 'u2')
    expect(next).toHaveLength(2)
    expect(next[1]).toMatchObject({ text: 'newer', uuid: 'u2' })
  })

  it('fork lineage の同 text 別 uuid event を正しく append する (= 2026-06-23 退行 fix を維持)', () => {
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

  it('eventUuid なしの event でも append する (= uuid 欠落は useChatStorage filter で persist 阻止される)', () => {
    const cur = [confirmed('older', 'u1')]
    const next = reconcileUserMessage(cur, 'brand new text', undefined)
    expect(next).toHaveLength(2)
    expect(next[1]).toMatchObject({ role: 'user', text: 'brand new text', uuid: null })
  })

  it('連投 (= optimistic 2 個並走) で SSE event 1 個来たら末尾近傍の 1 個を pop、 残り 1 個は optimistic のまま', () => {
    const cur = [opt('一個目'), opt('二個目')]
    const next = reconcileUserMessage(cur, '二個目', 'u2')
    expect(next).toHaveLength(2)
    expect(next[0].optimistic).toBe(true)
    expect(next[1]).toMatchObject({ text: '二個目', uuid: 'u2' })
    expect(next[1].optimistic).toBeUndefined()
  })

  it('構造的に重複が起きない: ghost (= uuid 持ち confirmed) と同 text 別 uuid event が来ても 2 件並ぶだけで append が走る (= 重複表示 root cause は ghost 側を生まない useChatStorage filter で根治)', () => {
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
