// Golden path: ask-user-question feature.
// Inject an AskUserQuestion tool_use; the bubble surfaces in the chat.

import { test, expect } from '@playwright/test'
import { seedSession, appendEvent } from '../../helpers/fixture.js'
import { openClient } from '../../helpers/pwa.js'

const SID = 'ses_e2echatgld'

test.describe('golden: ask-user-question', () => {
  test('AskUserQuestion tool_use surfaces the choice bubble', async ({ page, request }) => {
    const seeded = await seedSession(request, 'e2e-chat-golden')
    await openClient(page, { sid: SID })

    appendEvent(seeded.jsonl_path, {
      type: 'assistant',
      uuid: 'a-aq-001',
      message: {
        id: 'msg_aq_01',
        role: 'assistant',
        content: [
          { type: 'text', text: 'Which color?' },
          {
            type: 'tool_use',
            id: 'tool_aq_01',
            name: 'AskUserQuestion',
            input: {
              questions: [{
                question: 'Which color do you prefer?',
                header: 'preference',
                multiSelect: false,
                options: [
                  { label: 'Red', description: 'crimson' },
                  { label: 'Blue', description: 'azure' },
                ],
              }],
            },
          },
        ],
        stop_reason: 'tool_use',
        model: 'claude-opus-4-7',
      },
      timestamp: new Date(0).toISOString(),
    })

    const bubble = page.locator('[data-testid=ask-user-question-bubble]').first()
    await expect(bubble).toBeVisible({ timeout: 10_000 })
    await expect(bubble.locator('[data-testid=ask-user-question-text]')).toContainText('Which color')
    // Both options render as buttons (= scoped inside this bubble).
    await expect(bubble.getByRole('button', { name: /Red/ })).toBeVisible()
    await expect(bubble.getByRole('button', { name: /Blue/ })).toBeVisible()
  })
})
