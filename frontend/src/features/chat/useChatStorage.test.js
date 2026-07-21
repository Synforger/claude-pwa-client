import { describe, it, expect } from 'vitest'
import { isPersistableMessage, isStorablePersistedMessage, persistSig } from './useChatStorage.js'

// 2026-06-24 server-of-truth 純化: localStorage 永続化境界の唯一の真値となる純関数 test。
// 重複バグ root cause (= uuid なし user 行が ghost として復活し SSE event との dedup を破る)
// の構造的根治はここで保証される。 reconcileUserMessage 側の dedup 簡素化と対になる境界。

describe('isPersistableMessage', () => {
  it('confirmed user with a uuid passes', () => {
    expect(isPersistableMessage({ role: 'user', text: 'hi', uuid: 'u1' })).toBe(true)
  })

  it('optimistic user is rejected (ephemeral, render-only)', () => {
    expect(isPersistableMessage({ role: 'user', text: 'hi', uuid: 'u1', optimistic: true })).toBe(false)
  })

  it('sendFailed user is rejected (ephemeral awaiting resend; persisting it creates ghosts)', () => {
    expect(isPersistableMessage({ role: 'user', text: 'hi', uuid: 'u1', sendFailed: true })).toBe(false)
  })

  it('user without a uuid is rejected (duplicate-display root cause; also auto-cleans old caches)', () => {
    expect(isPersistableMessage({ role: 'user', text: 'hi' })).toBe(false)
    expect(isPersistableMessage({ role: 'user', text: 'hi', uuid: null })).toBe(false)
    expect(isPersistableMessage({ role: 'user', text: 'hi', uuid: '' })).toBe(false)
  })

  it('agent messages pass with or without a uuid (persisted even while streaming)', () => {
    expect(isPersistableMessage({ role: 'agent', text: 'reply', uuid: 'a1' })).toBe(true)
    expect(isPersistableMessage({ role: 'agent', text: 'reply' })).toBe(true)
    expect(isPersistableMessage({ role: 'agent', text: '', streaming: true })).toBe(true)
  })

  it('system messages (session_end markers etc.) pass', () => {
    expect(isPersistableMessage({ role: 'system', kind: 'session_end', ts: 1 })).toBe(true)
  })

  it('null / undefined are rejected', () => {
    expect(isPersistableMessage(null)).toBe(false)
    expect(isPersistableMessage(undefined)).toBe(false)
  })
})

// 発熱根治 (= 2026-07-21): streaming 中の in-flight メッセージを localStorage 書込対象から
// 外す。 これで streaming 中に配列参照が毎トークン変わっても永続化内容 (= 確定分) は不変
// になり、 「毎 250ms 全履歴再圧縮」 の worker CPU (= 端末発熱の主因) が止まる。 in-flight
// は jsonl replay で復元されるので落としても実データ損失なし。
describe('isStorablePersistedMessage (localStorage 書込境界)', () => {
  it('streaming 中の agent メッセージは書込対象から除外 (= in-flight は persist しない)', () => {
    expect(isStorablePersistedMessage({ role: 'agent', text: '', streaming: true })).toBe(false)
    // 確定した (streaming フラグの無い) agent は従来通り persist する
    expect(isStorablePersistedMessage({ role: 'agent', text: 'done', uuid: 'a1' })).toBe(true)
  })

  it('isPersistableMessage で弾かれるものはこちらでも弾かれる', () => {
    expect(isStorablePersistedMessage({ role: 'user', text: 'hi', optimistic: true })).toBe(false)
    expect(isStorablePersistedMessage(null)).toBe(false)
  })
})

describe('persistSig (冗長圧縮スキップの署名)', () => {
  it('確定分が同じなら署名は不変 (= streaming の in-flight は既に除外済みなので圧縮を打たない)', () => {
    const finalized = [
      { role: 'user', text: 'q', uuid: 'u1' },
      { role: 'agent', text: 'a1', uuid: 'a1' },
    ]
    // 同一確定集合 → 同一署名 → save loop は圧縮スキップ
    expect(persistSig(finalized)).toBe(persistSig(finalized.slice()))
  })

  it('確定メッセージが 1 件増えると署名が変わる (= ターン確定時に 1 回だけ保存)', () => {
    const before = [{ role: 'agent', text: 'a1', uuid: 'a1' }]
    const after = [...before, { role: 'agent', text: 'a2', uuid: 'a2' }]
    expect(persistSig(after)).not.toBe(persistSig(before))
  })

  it('末尾メッセージの本文長が変わると署名が変わる (= 確定分の in-place 編集も取りこぼさない)', () => {
    const a = [{ role: 'agent', text: 'short', uuid: 'a1' }]
    const b = [{ role: 'agent', text: 'short + more', uuid: 'a1' }]
    expect(persistSig(a)).not.toBe(persistSig(b))
  })

  it('空配列は安定した署名を返す', () => {
    expect(persistSig([])).toBe('0')
  })
})
