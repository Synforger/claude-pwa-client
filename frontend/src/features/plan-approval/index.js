// features/plan-approval 配線 entry。

import { register as registerFeature } from '../../registry/featureRegistry.js'

import './PlanApprovalBubble.jsx'

registerFeature('plan-approval', { dispatch: () => null })
