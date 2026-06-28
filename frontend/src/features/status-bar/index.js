// features/status-bar 配線 entry (= 設計書 § 9-6 step 5)。 W2 Phase F-status-bar 段階: 物理移送
// + SSE singleton 経由化のみ完了。 v2 state/registry 経由の深化は後続 commit で。

import './StatusBar.jsx'
import './useStatus.js'

// TODO: 後続 commit で
//   import { register as registerStream } from '../../registry/streamRegistry.js'
//   registerStream('budget', { dispatch: handleBudget })
//   registerStream('mode', { dispatch: handleMode })
//   registerStream('permission_mode', { dispatch: handlePermissionMode })
//   registerStream('pr_link', { dispatch: handlePrLink })
