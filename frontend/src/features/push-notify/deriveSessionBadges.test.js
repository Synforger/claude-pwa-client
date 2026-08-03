// deriveSessionBadges の waitingInput 合流 (= 2026-07-15 裏セッション質問待ちバッジ)。
import { describe, it, expect } from 'vitest'
import { deriveSessionBadges } from './useSessionBadges.js'

describe('deriveSessionBadges waitingInput', () => {
  it('messages が空でも waitingInput=true の裏 sid に ? バッジが点く', () => {
    const { sessionBadges } = deriveSessionBadges({
      sids: ['a', 'b'], activeSid: 'a',
      messages: {}, loading: {}, unreadDone: {},
      waitingInput: { b: true },
    })
    expect(sessionBadges.b).toEqual({ kind: 'pending', label: '?' })
    expect(sessionBadges.a).toBe(null)  // active かつ推論中でないので印なし
  })

  it('waitingInput 無指定でも従来の messages 由来判定は生きる (= 後方互換)', () => {
    const { sessionBadges } = deriveSessionBadges({
      sids: ['b'], activeSid: 'a',
      messages: { b: [{ askUserQuestion: { answered: false } }] },
      loading: {}, unreadDone: {},
    })
    expect(sessionBadges.b).toEqual({ kind: 'pending', label: '?' })
  })
})

// 開いているタブでも「推論中」 だけは一覧に残す (= 2026-08-03 要望)。 一覧は「今どのタブが
// 動いているか」 の一覧でもあり、 開いた瞬間に印が消えると走っているか読めなくなる。
// 未読 / 質問待ちは画面を見れば分かるので従来どおり消す。
describe('deriveSessionBadges — active タブの扱い', () => {
  const base = { sids: ['a'], activeSid: 'a', messages: {}, unreadDone: {}, waitingInput: {} }

  it('推論中なら active でも青丸を出す', () => {
    const { sessionBadges } = deriveSessionBadges({ ...base, loading: { a: true } })
    expect(sessionBadges.a).toEqual({ kind: 'processing', label: '●' })
  })

  it('未読は active では消す', () => {
    const { sessionBadges, unreadCount } = deriveSessionBadges({
      ...base, loading: {}, unreadDone: { a: true },
    })
    expect(sessionBadges.a).toBe(null)
    expect(unreadCount).toBe(0)
  })

  it('質問待ちも active では消す (= 画面に質問が出ている)', () => {
    const { sessionBadges } = deriveSessionBadges({
      ...base, loading: {}, waitingInput: { a: true },
    })
    expect(sessionBadges.a).toBe(null)
  })

  it('推論中と質問待ちが重なったら推論中を優先する', () => {
    const { sessionBadges } = deriveSessionBadges({
      ...base, loading: { a: true }, waitingInput: { a: true },
    })
    expect(sessionBadges.a).toEqual({ kind: 'processing', label: '●' })
  })

  it('active でない sid の判定順は従来どおり (= 質問待ち > 推論中 > 未読)', () => {
    const { sessionBadges } = deriveSessionBadges({
      sids: ['b'], activeSid: 'a', messages: {},
      loading: { b: true }, unreadDone: { b: true }, waitingInput: { b: true },
    })
    expect(sessionBadges.b).toEqual({ kind: 'pending', label: '?' })
  })
})
