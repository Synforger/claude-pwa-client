// features/ask-user-question 配線 entry。

import { register as registerStream } from '../../registry/streamRegistry.js'

import './AskUserQuestionBubble.jsx'

registerStream('ask_user_question', { dispatch: () => null }, { replace: true })
