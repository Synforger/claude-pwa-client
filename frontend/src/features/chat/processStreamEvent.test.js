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
