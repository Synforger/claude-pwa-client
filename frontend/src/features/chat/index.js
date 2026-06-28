// features/chat 配線 entry (= 設計書 § 9-6 step 5 + W2 真の完成、 ADR-026 + 残骸 sweep)。
//
// 旧 src/messageRegistry.js (= v1 真値 121 行、 7 kind hardcoded) は本 file に集約。
// registry/messageRegistry.js が createRegistry pattern + getEntry(kind) を提供、
// 各 feature の配線 entry が真の { fromEvent, Render } を register する形に統一。
// ADR-010 lifecycle 契約で handler.dispatch 必須なので、 message entry は no-op dispatch
// + fromEvent / Render を併載する (= dispatch は呼ばれない、 entry は getEntry(kind) で引かれる)。

import { register as registerStream } from '../../registry/streamRegistry.js'
import { register as registerMessage } from '../../registry/messageRegistry.js'

// 移送した chat file への副作用 import (= bundler が tree-shake せず features/chat/ 配下を保持)
import './useChatStream.js'
import './useChatStorage.js'
import './processStreamEvent.js'
import './reconcileUserMessage.js'
import './useStreamBuffer.js'
import './MessageItem.jsx'
import './MessageRenderer.jsx'
import './ChatInput.jsx'
import './SystemMessages.jsx'

// SystemMessages 内の Render component を message registry に紐付ける
import {
  CompactBanner,
  SessionEndBanner,
  ApiErrorCard,
  AttachmentCard,
  HookErrorCard,
  SystemNoteCard,
} from './SystemMessages.jsx'

const noopDispatch = () => null

// SSE event → chat 描画経路を streamRegistry に登録 (= 設計書 § 9-6 step 5)。
registerStream('user_message',       { dispatch: noopDispatch })
registerStream('assistant',          { dispatch: noopDispatch })
registerStream('result',             { dispatch: noopDispatch })
registerStream('ask_user_question',  { dispatch: noopDispatch })
registerStream('attachment',         { dispatch: noopDispatch })
registerStream('system',             { dispatch: noopDispatch })
registerStream('system_error',       { dispatch: noopDispatch })
registerStream('hook_error',         { dispatch: noopDispatch })
registerStream('system_note',        { dispatch: noopDispatch })
registerStream('turn_duration',      { dispatch: noopDispatch })

// system message kind → { fromEvent(event) -> extra props, Render(msg) -> JSX } の真値配線。
// 新 kind 追加は本 file (or 該当 feature の index.js) に 1 ブロック足すだけで完結。

// 会話圧縮タイミング。 SDK からは事後通知のみ (= 結果カードのみ)。
registerMessage('compact', {
  dispatch: noopDispatch,
  fromEvent: (event) => {
    const meta = event.compactMetadata || {}
    return {
      trigger: meta.trigger || null,
      preTokens: typeof meta.preTokens === 'number' ? meta.preTokens : null,
      postTokens: typeof meta.postTokens === 'number' ? meta.postTokens : null,
      durationMs: typeof meta.durationMs === 'number' ? meta.durationMs : null,
    }
  },
  Render: CompactBanner,
})

// セッション終了の区切りバナー。 SDK event 由来でなく backend tail が直接挿入する (= fromEvent null)。
registerMessage('session_end', {
  dispatch: noopDispatch,
  fromEvent: null,
  Render: SessionEndBanner,
})

// Anthropic API エラー (= 529 / 401 / network down 等)。 赤い inline カード。
registerMessage('api_error', {
  dispatch: noopDispatch,
  fromEvent: (event) => ({
    formatted: event.formatted || 'API error',
    status: event.status ?? null,
    requestId: event.requestId || null,
    isNetworkDown: !!event.isNetworkDown,
    retryInMs: typeof event.retryInMs === 'number' ? event.retryInMs : null,
    retryAttempt: typeof event.retryAttempt === 'number' ? event.retryAttempt : null,
    timestamp: event.timestamp || null,
  }),
  Render: ApiErrorCard,
})

// hooks 実行が non-blocking で失敗した記録。 黄色 inline 警告。
registerMessage('hook_error', {
  dispatch: noopDispatch,
  fromEvent: (event) => ({
    hookName: event.hookName || '',
    hookEvent: event.hookEvent || '',
    exitCode: event.exitCode ?? null,
    stderr: event.stderr || '',
    stdout: event.stdout || '',
    command: event.command || '',
    durationMs: event.durationMs ?? null,
  }),
  Render: HookErrorCard,
})

// local_command (/model 等) / scheduled_task_fire (/loop wakeup) の発火記録。
registerMessage('system_note', {
  dispatch: noopDispatch,
  fromEvent: (event) => ({
    subtype: event.subtype || '',
    content: event.content || '',
  }),
  Render: SystemNoteCard,
})

// queued_command / task_reminder / skill_listing 他を折りたたみカードで表示。
registerMessage('attachment', {
  dispatch: noopDispatch,
  fromEvent: (event) => ({
    subtype: event.subtype || 'unknown',
    attachment: event.attachment || {},
  }),
  Render: AttachmentCard,
})

// task kind (= background task 完了通知) は features/tasks/index.js で register する (= 責務分離)。
