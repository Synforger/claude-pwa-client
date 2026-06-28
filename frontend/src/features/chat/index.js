// features/chat 配線 entry (= 設計書 § 9-6 step 5)。
// W2 完了判定 1: registry.register を呼ぶ。 実 dispatch は v1 useChatStream + processStreamEvent
// 経路を継続使用 (= 中身改変最小、 ADR-006 server-of-truth 整合維持)、 register は wiring signal。
// v2 state/registry 経路への深化 (= dispatch handler 内で state.messages 等を直接更新) は後続。

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

// SSE event → chat 描画経路を streamRegistry に登録 (= 設計書 § 9-6 step 5)。
// dispatch は後続 commit で本格化、 現状は v1 経路 (= useChatStream 内 processStreamEvent) を継続。
const noopDispatch = () => null
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

// system message kind → render component (= v1 messageRegistry 流儀)。
// W2 連携深化で messageRegistry.getEntry(kind) 経由に切替予定、 現状は registry 上に「kind 存在」 のみ宣言。
const noopEntry = { dispatch: noopDispatch }
registerMessage('compact',     noopEntry)
registerMessage('api_error',   noopEntry)
registerMessage('hook_error',  noopEntry)
registerMessage('system_note', noopEntry)
registerMessage('attachment',  noopEntry)
registerMessage('task',        noopEntry)
