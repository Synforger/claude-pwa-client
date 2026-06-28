// features/chat 配線 entry (= self-register、 設計書 § 9-6 step 5)。
// App.jsx は本 file を import するだけで chat 機能が登録される構造を目指す (= ADR-010、 streamRegistry).
//
// W2 Phase F-chat 段階: v1 file を物理移送 + import path 修正のみ完了。 v2 state/registry 経由への
// 配線 (= streamRegistry.register('user_message', { dispatch: ... }) 等) は v1 hooks の中身を
// 段階的に v2 store 経由に書換える後続 commit で本格化する。

// import path を解析可能にする副作用 import (= 移送した chat file への参照を 1 箇所に集約、
// Phase G で旧 path 経路を撤去する時の起点)。
import './useChatStream.js'
import './useChatStorage.js'
import './processStreamEvent.js'
import './reconcileUserMessage.js'
import './useStreamBuffer.js'
import './MessageItem.jsx'
import './MessageRenderer.jsx'
import './ChatInput.jsx'
import './SystemMessages.jsx'

// TODO: v2 state 経路への深化と一緒に streamRegistry / messageRegistry への register を入れる
//   import { register as registerStream } from '../../registry/streamRegistry.js'
//   import { register as registerMessage } from '../../registry/messageRegistry.js'
//   registerStream('user_message', { dispatch: (event) => { ... v2 state 経路 ... } })
//   registerMessage('compact', { fromEvent, Render: CompactBanner })
