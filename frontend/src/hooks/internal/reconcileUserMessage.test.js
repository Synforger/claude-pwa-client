import { describe, it, expect } from 'vitest'
import { reconcileUserMessage } from './reconcileUserMessage.js'

const opt = (text, extra = {}) => ({ id: text, role: 'user', text, optimistic: true, ...extra })

describe('reconcileUserMessage', () => {
  it('exact-match の楽観 user を confirm し新規追加しない', () => {
    const cur = [opt('hello')]
    const next = reconcileUserMessage(cur, 'hello', 'u1')
    expect(next).toHaveLength(1)
    expect(next[0].optimistic).toBe(false)
    expect(next[0].uuid).toBe('u1')
  })

  it('既知 uuid なら変更しない (= 同一参照を返す)', () => {
    const cur = [{ id: 'a', role: 'user', text: 'hi', uuid: 'u1', optimistic: false }]
    expect(reconcileUserMessage(cur, 'hi', 'u1')).toBe(cur)
  })

  it('連投が結合された JSONL バブルは追加せず、 部分一致の楽観を confirm する (中間 regression)', () => {
    // ユーザは 2 回送信。 claude が推論中の連投を 1 プロンプトに結合して受領 →
    // JSONL は結合テキスト。 3 つ目の結合バブルを出さないこと。
    const cur = [opt('そんな当たり前のこと書く必要ある？？'), opt('後半の観点ね。')]
    const fusedText = 'そんな当たり前のこと書く必要ある？？後半の観点。'
    const next = reconcileUserMessage(cur, fusedText, 'u9')
    // 新規バブルは増えない (= 2 のまま)
    expect(next).toHaveLength(2)
    // 部分文字列一致した 1 件目は confirm 済みに、 一致しない 2 件目は楽観のまま
    expect(next[0].optimistic).toBe(false)
    expect(next[1].optimistic).toBe(true)
    // 結合テキストの user バブルは存在しない
    expect(next.some(m => m.text === fusedText)).toBe(false)
  })

  it('該当する楽観が無ければ (= replay) user バブルを新規追加する', () => {
    const cur = []
    const next = reconcileUserMessage(cur, 'reloaded prompt', 'u2')
    expect(next).toHaveLength(1)
    expect(next[0]).toMatchObject({ role: 'user', text: 'reloaded prompt', uuid: 'u2' })
  })

  it('添付付き (= [添付ファイル: ...]) は fileNames 持ち楽観と置換する', () => {
    const cur = [opt('画像送るね', { fileNames: ['a.png'] })]
    const next = reconcileUserMessage(cur, '画像送るね [添付ファイル: /tmp/x.png]', 'u3')
    expect(next).toHaveLength(1)
    expect(next[0].optimistic).toBe(false)
    expect(next[0].fileNames).toEqual(['a.png'])
  })

  it('同 uuid の既知 event なら dedup する (= 唯一の正当な dedup 経路)', () => {
    const cur = [{ id: 'a', role: 'user', text: 'hello', uuid: 'u-known', optimistic: false }]
    // 同じ uuid の event が再送 / replay されたら no-op
    expect(reconcileUserMessage(cur, 'hello', 'u-known')).toBe(cur)
  })

  it('fork lineage 内の「同 text 別 uuid」 user message が replay されたら正しく append する (= 2026-06-23 退行 fix)', () => {
    // fork は親 jsonl の lineage をコピーするので、 8 件以内に同 text の user message が
    // 並ぶケースは普通にある (= 同じ言葉で複数回投げた会話を fork した時等)。 旧版
    // (= 5826538) の LOOKBACK_DEDUP は ここで誤発火 → 2 件目以降が消える → 「fork タブに
    // 反映されない」 退行を起こしていた。 新版は uuid が異なる以上は正当な別 message として扱う。
    const confirmed = (text, uuid) => ({ id: uuid, role: 'user', text, uuid, optimistic: false })
    const cur = [
      confirmed('やり直して', 'u-fork-1'),
      { id: 'a1', role: 'agent', text: '了解', uuid: 'a1' },
      confirmed('やり直して', 'u-fork-2'),
      { id: 'a2', role: 'agent', text: '再実行します', uuid: 'a2' },
    ]
    const next = reconcileUserMessage(cur, 'やり直して', 'u-fork-3')
    expect(next).not.toBe(cur)
    expect(next).toHaveLength(5)
    expect(next[4]).toMatchObject({ role: 'user', text: 'やり直して', uuid: 'u-fork-3' })
  })

  it('eventUuid なしの event も append する (= 旧 5826508 の安全弁撤回、 ghost resurface は useChatStorage 側で塞ぐ)', () => {
    const cur = [{ id: 'a', role: 'user', text: 'older', uuid: 'u1', optimistic: false }]
    const next = reconcileUserMessage(cur, 'brand new text', undefined)
    expect(next).toHaveLength(2)
    expect(next[1]).toMatchObject({ role: 'user', text: 'brand new text', uuid: null })
  })
})
