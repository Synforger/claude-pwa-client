import { describe, it, expect, vi } from 'vitest'
// processStreamEvent は messageRegistry.getEntry(kind) で fromEvent / Render を引く。
// 各 feature が自分の kind を register するのは features/<x>/index.js の side-effect import なので、
// test では register が走らない。 該当 feature を side-effect import して registry を hydrate する。
import './index.js'                  // features/chat の全 message kind (= compact/api_error 等) を register
import '../tasks/index.js'           // features/tasks の task kind を register
import { extractAskAnswer, processStreamEvent } from './processStreamEvent.js'

// claude は 1 つの AssistantMessage を thinking / text / tool_use の別 JSONL 行
// (= 別フレーム、 同 message.id) に分けて書く。 それらが同じ rAF 窓で coalesce される時、
// 後続フレームが前フレームの text/thinking を空で上書きしてはいけない (= 中間出力が消える bug)。
// processStreamEvent は副作用を deps 経由にしているので、 共有 buf を注入して検証する。

function emptyBuf() {
  return { text: null, thinking: null, newTools: [], needsNewBubble: false, uuid: null, dirty: false }
}

function makeDeps(buf) {
  return {
    setMessages: vi.fn(),
    setApiKeySource: vi.fn(),
    cancelAndFlush: vi.fn(),
    scheduleFlush: vi.fn(),
    streamBufRef: { current: {} },
    bufFor: () => buf,
  }
}

function assistantEvent(block, uuid) {
  return { type: 'assistant', uuid, message: { content: [block] } }
}

describe('processStreamEvent — same-uuid frame aggregation (intermediate-output regression)', () => {
  it('a following tool_use frame does not blank out text/thinking of the same message.id', () => {
    const buf = emptyBuf()
    const deps = makeDeps(buf)
    const sid = 's1'

    processStreamEvent(deps, sid, assistantEvent({ type: 'thinking', thinking: '考え中' }, 'X'))
    processStreamEvent(deps, sid, assistantEvent({ type: 'text', text: '実行します' }, 'X'))
    processStreamEvent(deps, sid, assistantEvent({ type: 'tool_use', name: 'Bash', id: 't1', input: {} }, 'X'))

    expect(buf.text).toBe('実行します')
    expect(buf.thinking).toBe('考え中')
    expect(buf.newTools).toHaveLength(1)
    expect(buf.uuid).toBe('X')
  })

  it('a different uuid flushes the previous message first', () => {
    const buf = emptyBuf()
    const deps = makeDeps(buf)

    processStreamEvent(deps, 's1', assistantEvent({ type: 'text', text: 'A' }, 'X'))
    processStreamEvent(deps, 's1', assistantEvent({ type: 'text', text: 'B' }, 'Y'))

    expect(deps.cancelAndFlush).toHaveBeenCalled()
  })
})

// setMessages の reducer を実際に適用して messages state の変化を検証するための deps。
function makeStatefulDeps(initial = {}) {
  let state = initial
  const deps = {
    setMessages: vi.fn(fn => { state = fn(state) }),
    setApiKeySource: vi.fn(),
    cancelAndFlush: vi.fn(),
    scheduleFlush: vi.fn(),
    streamBufRef: { current: {} },
    bufFor: () => emptyBuf(),
  }
  return { deps, get: () => state }
}

function askEvent(tool_use_id, questions = [{ question: 'Q?', options: [{ label: 'A' }] }]) {
  return { type: 'ask_user_question', tool_use_id, input: { questions } }
}

function toolResultEvent(tool_use_id, content) {
  return { type: 'user', message: { content: [{ type: 'tool_result', tool_use_id, content }] } }
}

describe('processStreamEvent — AskUserQuestion unstick behaviour', () => {
  it('question bubbles are created with streaming:false (stops the thinking indicator)', () => {
    const { deps, get } = makeStatefulDeps({ s1: [] })
    processStreamEvent(deps, 's1', askEvent('toolu_1'))
    const bubble = get().s1.at(-1)
    expect(bubble.askUserQuestion.tool_use_id).toBe('toolu_1')
    expect(bubble.askUserQuestion.answered).toBe(false)
    expect(bubble.streaming).toBe(false)
  })

  it('streaming drops to false even when co-located in an existing agent bubble', () => {
    const init = { s1: [{ id: 'a', role: 'agent', text: '本文', streaming: true }] }
    const { deps, get } = makeStatefulDeps(init)
    processStreamEvent(deps, 's1', askEvent('toolu_2'))
    const bubble = get().s1.at(-1)
    expect(bubble.text).toBe('本文')
    expect(bubble.askUserQuestion.tool_use_id).toBe('toolu_2')
    expect(bubble.streaming).toBe(false)
  })

  it('a tool_result folds the matching question bubble to answered + streaming:false (rescues terminal-side answers)', () => {
    const init = {
      s1: [{
        id: 'a', role: 'agent', streaming: true,
        askUserQuestion: { tool_use_id: 'toolu_3', questions: [], answered: false, selectedAnswer: null },
      }],
    }
    const { deps, get } = makeStatefulDeps(init)
    processStreamEvent(deps, 's1', toolResultEvent('toolu_3', '選択: はい'))
    const bubble = get().s1.find(m => m.askUserQuestion?.tool_use_id === 'toolu_3')
    expect(bubble.askUserQuestion.answered).toBe(true)
    expect(bubble.streaming).toBe(false)
    expect(bubble.askUserQuestion.selectedAnswer).toBe('選択: はい')
  })

  it('selectedAnswer from a chat-side answer is not overwritten by the tool_result', () => {
    const init = {
      s1: [{
        id: 'a', role: 'agent', streaming: false,
        askUserQuestion: { tool_use_id: 'toolu_4', questions: [], answered: false, selectedAnswer: 'B' },
      }],
    }
    const { deps, get } = makeStatefulDeps(init)
    processStreamEvent(deps, 's1', toolResultEvent('toolu_4', 'harness が整形した別文'))
    const bubble = get().s1.find(m => m.askUserQuestion?.tool_use_id === 'toolu_4')
    expect(bubble.askUserQuestion.answered).toBe(true)
    expect(bubble.askUserQuestion.selectedAnswer).toBe('B')
  })

  it('a tool_result with a different tool_use_id does not fold the question bubble', () => {
    const init = {
      s1: [{
        id: 'a', role: 'agent', streaming: true,
        askUserQuestion: { tool_use_id: 'toolu_5', questions: [], answered: false, selectedAnswer: null },
      }],
    }
    const { deps, get } = makeStatefulDeps(init)
    processStreamEvent(deps, 's1', toolResultEvent('toolu_other', 'x'))
    const bubble = get().s1.find(m => m.askUserQuestion?.tool_use_id === 'toolu_5')
    expect(bubble.askUserQuestion.answered).toBe(false)
    expect(bubble.streaming).toBe(true)
  })
})

describe('processStreamEvent — task_notification (background-task completion card)', () => {
  function taskEvent(uuid, over = {}) {
    return {
      type: 'task_notification', uuid,
      summary: 'Background command "x" completed (exit code 0)',
      status: 'completed', outputFile: 'REDACTED_PATH/p/s/tasks/x.output',
      exitCode: 0, ...over,
    }
  }

  it('pushed as a system/task bubble (never a user bubble)', () => {
    const { deps, get } = makeStatefulDeps({ s1: [] })
    processStreamEvent(deps, 's1', taskEvent('t1'))
    const bubble = get().s1.at(-1)
    expect(bubble.role).toBe('system')
    expect(bubble.kind).toBe('task')
    expect(bubble.exitCode).toBe(0)
    expect(bubble.outputFile).toContain('x.output')
  })

  it('a replay of the same uuid does not append a duplicate', () => {
    const { deps, get } = makeStatefulDeps({ s1: [] })
    processStreamEvent(deps, 's1', taskEvent('t2'))
    processStreamEvent(deps, 's1', taskEvent('t2'))
    expect(get().s1.filter(m => m.kind === 'task')).toHaveLength(1)
  })
})

describe('extractAskAnswer (= AskUserQuestion tool_result の包装剥がし)', () => {
  it('harness 包装から回答本文だけを抜く (= 実 wire 形式)', () => {
    const raw = 'Your questions have been answered: "最終往復テスト (#147)。試すこと: ① ↓ を連打..."="全部追従した (合格)". You can now continue with these answers in mind.'
    expect(extractAskAnswer(raw)).toBe('全部追従した (合格)')
  })

  it('包装が無い形式はそのまま返す (= 後方互換)', () => {
    expect(extractAskAnswer('OAuth')).toBe('OAuth')
    expect(extractAskAnswer('')).toBe(null)
    expect(extractAskAnswer(null)).toBe(null)
  })

  it('回答内に引用符が含まれても末尾の閉じだけ剥がす', () => {
    const raw = 'Your questions have been answered: "Q"="彼は "OK" と言った". You can now continue with these answers in mind.'
    expect(extractAskAnswer(raw)).toBe('彼は "OK" と言った')
  })
})

// ---------------------------------------------------------------------------
// 追加契約 (= 2026-07-07 coverage 増強): system カード族 / result / turn_duration /
// tool_result 紐付け / prompt_state 振り分け
// ---------------------------------------------------------------------------

import { getSnapshot as getPromptSnapshot, clearPromptState } from '../../state/promptState.js'
import { MAX_MESSAGES } from '../../constants.js'

describe('processStreamEvent — system カード族', () => {
  it.each([
    ['compact_boundary 系', { type: 'system', subtype: 'compact_boundary', uuid: 'u1' }, 'compact'],
    ['system_error', { type: 'system_error', uuid: 'u2', message: 'overloaded' }, 'api_error'],
    ['hook_error', { type: 'hook_error', uuid: 'u3', hook: 'x', error: 'boom' }, 'hook_error'],
    ['system_note', { type: 'system_note', uuid: 'u4', note: 'fired' }, 'system_note'],
    ['attachment', { type: 'attachment', uuid: 'u5', kind: 'queued_command' }, 'attachment'],
  ])('%s は system バブルとして積まれる + 同 uuid replay は重複しない', (_label, event, kind) => {
    const { deps, get } = makeStatefulDeps({ s1: [] })
    processStreamEvent(deps, 's1', event)
    processStreamEvent(deps, 's1', event)  // replay
    const bubbles = get().s1.filter(m => m.role === 'system' && m.kind === kind)
    expect(bubbles).toHaveLength(1)
    expect(bubbles[0].uuid).toBe(event.uuid)
  })

  it('MAX_MESSAGES 到達時は先頭を捨てて末尾に積む (= 総数維持)', () => {
    const full = Array.from({ length: MAX_MESSAGES }, (_, i) => ({
      id: `m${i}`, role: 'agent', text: String(i),
    }))
    const { deps, get } = makeStatefulDeps({ s1: full })
    processStreamEvent(deps, 's1', { type: 'system_note', uuid: 'u-trim', note: 'x' })
    const arr = get().s1
    expect(arr).toHaveLength(MAX_MESSAGES)
    expect(arr[0].id).toBe('m1')            // 先頭 1 件が落ちた
    expect(arr.at(-1).kind).toBe('system_note')
  })
})

describe('processStreamEvent — result / turn_duration', () => {
  it('result は最後の agent バブルに meta を埋めて streaming を落とす', () => {
    const init = { s1: [{ id: 'a', role: 'agent', text: 'x', streaming: true }] }
    const { deps, get } = makeStatefulDeps(init)
    processStreamEvent(deps, 's1', {
      type: 'result', total_cost_usd: 0.5, num_turns: 3, duration_ms: 1200,
      stop_reason: 'end_turn',
    })
    const last = get().s1.at(-1)
    expect(last.meta.cost_usd).toBe(0.5)
    expect(last.meta.num_turns).toBe(3)
    expect(last.meta.stop_reason).toBe('end_turn')
    expect(last.streaming).toBe(false)
  })

  it('最後が agent でなければ result は何もしない', () => {
    const init = { s1: [{ id: 'u', role: 'user', text: 'hi' }] }
    const { deps, get } = makeStatefulDeps(init)
    processStreamEvent(deps, 's1', { type: 'result', duration_ms: 1 })
    expect(get().s1.at(-1).meta).toBeUndefined()
  })

  it('turn_duration は parentUuid 一致の agent に duration_ms を書く', () => {
    const init = { s1: [
      { id: 'a1', role: 'agent', uuid: 'AM1', text: 'x' },
      { id: 'u1', role: 'user', text: 'y' },
    ] }
    const { deps, get } = makeStatefulDeps(init)
    processStreamEvent(deps, 's1', { type: 'turn_duration', parentUuid: 'AM1', durationMs: 999 })
    expect(get().s1[0].meta.duration_ms).toBe(999)
  })

  it('turn_duration は parentUuid 不一致なら最後の agent に fallback、 agent 不在なら無変化', () => {
    const init = { s1: [{ id: 'a1', role: 'agent', uuid: 'AM1', text: 'x' }] }
    const { deps, get } = makeStatefulDeps(init)
    processStreamEvent(deps, 's1', { type: 'turn_duration', parentUuid: 'nope', durationMs: 5 })
    expect(get().s1[0].meta.duration_ms).toBe(5)

    const empty = makeStatefulDeps({ s1: [{ id: 'u', role: 'user', text: 'z' }] })
    processStreamEvent(empty.deps, 's1', { type: 'turn_duration', durationMs: 5 })
    expect(empty.get().s1[0].meta).toBeUndefined()
  })
})

describe('processStreamEvent — tool_result 紐付け', () => {
  it('tool_use_id 一致の tool に result を埋め、 不一致 message は同一参照のまま', () => {
    const init = { s1: [
      { id: 'a1', role: 'agent', text: '', tools: [{ id: 't1', name: 'Bash' }] },
      { id: 'a2', role: 'agent', text: '', tools: [{ id: 't2', name: 'Read' }] },
    ] }
    const { deps, get } = makeStatefulDeps(init)
    processStreamEvent(deps, 's1', toolResultEvent('t1', 'output!'))
    const arr = get().s1
    expect(arr[0].tools[0].result).toEqual({ content: 'output!', is_error: false })
    expect(arr[1]).toBe(init.s1[1])  // 触ってない message は reference 同一 (= memo 維持)
  })

  it('どの tool にも一致しない tool_result は state 無変化 (= 同一 object を返す)', () => {
    const init = { s1: [{ id: 'a1', role: 'agent', text: '', tools: [{ id: 't1', name: 'Bash' }] }] }
    const { deps, get } = makeStatefulDeps(init)
    processStreamEvent(deps, 's1', toolResultEvent('unknown', 'x'))
    expect(get()).toBe(init)
  })
})

describe('processStreamEvent — prompt_state 振り分け', () => {
  it('prompt_state は messages に積まず promptState store に流す', () => {
    const { deps, get } = makeStatefulDeps({ s9: [] })
    processStreamEvent(deps, 's9', { type: 'prompt_state', state: 'text_prompt', excerpt: 'pw:' })
    expect(get().s9).toHaveLength(0)
    expect(getPromptSnapshot().bySid.s9?.state).toBe('text_prompt')
    clearPromptState('s9')
  })
})
