import { describe, it, expect } from 'vitest'
import { isPersistableMessage, isStorablePersistedMessage, toStorableForm, persistSig } from './useChatStorage.js'

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

  it('send_id を持たない optimistic user は依然として弾かれる (= ghost 防止)', () => {
    expect(isStorablePersistedMessage({ role: 'user', text: 'hi', optimistic: true })).toBe(false)
    expect(isStorablePersistedMessage(null)).toBe(false)
  })
})

// 「送信 → SSE 確定が返る前に繋ぎ直すと自分の送信が消える」 構造ギャップの根治
// (= 送信済み未確定 user を pending として永続化する境界)。 save / load 両端で通す projection。
describe('toStorableForm (永続化 projection)', () => {
  it('confirmed user (uuid) はそのまま保存', () => {
    const m = { id: 'i1', role: 'user', text: 'hi', uuid: 'u1', send_id: 's1' }
    expect(toStorableForm(m)).toBe(m)
  })

  it('送信済み未確定 user (send_id 付き optimistic) は pending として保存 (= 消えない)', () => {
    const m = {
      id: 'i1', role: 'user', text: 'hi', send_id: 's1', optimistic: true,
      imageUrls: ['blob:xxx'], imageRefs: ['idb-1'], fileNames: ['a.py'],
    }
    const out = toStorableForm(m)
    expect(out).not.toBeNull()
    expect(out.optimistic).toBeUndefined()   // optimistic フラグは落とす (= pending 化)
    expect(out.imageUrls).toBeUndefined()     // ObjectURL はリロードで失効するので落とす
    expect(out.send_id).toBe('s1')            // send_id は残す (= 復元後 uuid backfill の鍵)
    expect(out.imageRefs).toEqual(['idb-1'])  // IndexedDB key は残す (= 画像復元)
    expect(out.text).toBe('hi')
  })

  it('load で復元した pending (optimistic 無し・send_id 有り) は idempotent に通る', () => {
    const restored = { id: 'i1', role: 'user', text: 'hi', send_id: 's1' }
    expect(toStorableForm(restored)).toEqual(restored)
    expect(isStorablePersistedMessage(restored)).toBe(true)
  })

  it('sendFailed user は落とす (= ghost 防止)', () => {
    expect(toStorableForm({ role: 'user', text: 'hi', send_id: 's1', sendFailed: true })).toBeNull()
  })

  it('uuid も send_id も無い user は落とす', () => {
    expect(toStorableForm({ role: 'user', text: 'hi' })).toBeNull()
    expect(toStorableForm({ role: 'user', text: 'hi', optimistic: true })).toBeNull()
  })

  it('streaming (agent in-flight) は落とす', () => {
    expect(toStorableForm({ role: 'agent', text: '', streaming: true })).toBeNull()
  })

  it('確定 agent / system はそのまま通す', () => {
    const a = { role: 'agent', text: 'done', uuid: 'a1' }
    const s = { role: 'system', kind: 'session_end', ts: 1 }
    expect(toStorableForm(a)).toBe(a)
    expect(toStorableForm(s)).toBe(s)
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
