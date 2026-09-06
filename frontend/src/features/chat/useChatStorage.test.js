import { describe, it, expect } from 'vitest'
import { isPersistableMessage, isStorablePersistedMessage, toStorableForm, toStorableArray, persistSig } from './useChatStorage.js'

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

// 発熱根治 (= 2026-07-21) は「毎 250ms 全履歴再圧縮」 を止めるのが目的で、 そのために必要な
// のは **いま伸びている 1 件を保存対象から外すこと**だけ。 message 単体の判定で streaming を
// 弾くと、 ツールを呼んだ中間 bubble (= stop_reason が tool_use のまま確定するので streaming
// flag が落ちない) まで永久に保存されなくなる。 単体判定は streaming を見ない。
describe('isStorablePersistedMessage (localStorage 書込境界)', () => {
  it('streaming flag は単体判定に影響しない (= 中間 bubble も書込対象)', () => {
    expect(isStorablePersistedMessage({ role: 'agent', text: 'explaining', streaming: true })).toBe(true)
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

  it('streaming flag は保存形から外す (= 復元後に「…」 が残らない / path がリンク化される)', () => {
    const stored = toStorableForm({ role: 'agent', text: 'explaining', streaming: true })
    expect(stored).not.toBeNull()
    expect('streaming' in stored).toBe(false)
    expect(stored.text).toBe('explaining')
  })

  it('確定 agent / system はそのまま通す', () => {
    const a = { role: 'agent', text: 'done', uuid: 'a1' }
    const s = { role: 'system', kind: 'session_end', ts: 1 }
    expect(toStorableForm(a)).toBe(a)
    expect(toStorableForm(s)).toBe(s)
  })
})

// ツール実行の間に挟まる説明テキストが履歴から消えていた回帰の防波堤。
//
// claude は 1 ターンを複数の assistant message に分けて書き、 tool を呼んだ message の
// stop_reason は `tool_use` になる。 backend はその行で result event を出さないので、
// 中間 bubble の streaming flag は永久に落ちない。 「streaming = in-flight」 とみなして
// 単体で落とすと、 中間 bubble が 1 件も localStorage に載らず、 履歴 GET の replay 窓から
// 外れた過去は復元不能になる (= 実測 bubble 5,104 件中 4,626 件が保存されず、 うち 2,041 件が
// 地の文を持っていた)。
describe('toStorableArray (会話 1 本の永続化射影)', () => {
  const turn = () => ([
    { role: 'user', text: 'q', uuid: 'u1' },
    { role: 'agent', text: 'まず読みます', uuid: 'a1', tools: [{ id: 't1', name: 'Read' }], streaming: true },
    { role: 'agent', text: '次に直します', uuid: 'a2', tools: [{ id: 't2', name: 'Edit' }], streaming: true },
    { role: 'agent', text: '直りました', uuid: 'a3', streaming: false },
  ])

  it('確定済みの中間 bubble を全部保存する (= streaming flag が立っていても落とさない)', () => {
    const out = toStorableArray(turn())
    expect(out.map(m => m.uuid)).toEqual(['u1', 'a1', 'a2', 'a3'])
    expect(out.map(m => m.text)).toEqual(['q', 'まず読みます', '次に直します', '直りました'])
  })

  it('保存形からは streaming flag が消える', () => {
    const out = toStorableArray(turn())
    expect(out.every(m => !m.streaming)).toBe(true)
  })

  it('末尾が streaming の時だけ、 その 1 件を落とす (= いま伸びている bubble)', () => {
    const arr = turn()
    arr.push({ role: 'agent', text: '書きかけ', uuid: 'a4', streaming: true })
    const out = toStorableArray(arr)
    expect(out.map(m => m.uuid)).toEqual(['u1', 'a1', 'a2', 'a3'])
  })

  it('末尾が確定済みなら 1 件も落とさない', () => {
    const arr = turn()
    expect(toStorableArray(arr)).toHaveLength(4)
  })

  it('伸びている末尾を除いた内容は不変なので署名が動かない (= 再圧縮を打たない)', () => {
    const arr = turn()
    const sigBefore = persistSig(toStorableArray(arr))
    // 末尾の in-flight bubble に文字が積まれても保存内容は変わらない
    arr.push({ role: 'agent', text: 'a', uuid: 'a4', streaming: true })
    const sigMid = persistSig(toStorableArray(arr))
    arr[arr.length - 1] = { ...arr[arr.length - 1], text: 'ab' }
    const sigAfter = persistSig(toStorableArray(arr))
    expect(sigMid).toBe(sigBefore)
    expect(sigAfter).toBe(sigBefore)
  })

  it('user の永続化規律は据え置き (= optimistic な ghost は落ちる)', () => {
    const out = toStorableArray([
      { role: 'user', text: 'hi', optimistic: true },
      { role: 'agent', text: 'done', uuid: 'a1' },
    ])
    expect(out.map(m => m.uuid)).toEqual(['a1'])
  })

  it('空 / 非配列は空配列', () => {
    expect(toStorableArray([])).toEqual([])
    expect(toStorableArray(null)).toEqual([])
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
