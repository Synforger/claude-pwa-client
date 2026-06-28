// features/fork 配線 entry。 fork 機能の真値 logic は features/chat/MessageItem.jsx 内 fork button
// + features/session-drawer/useSessions.js の forkSession に分散 (= 設計書 § 9-6 step 4 中身改変最小)、
// 本 entry は wiring signal のみ。

import { register as registerFeature } from '../../registry/featureRegistry.js'

registerFeature('fork', { dispatch: () => null })
