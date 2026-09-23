// Golden path: ask-user-question feature.
// Inject an AskUserQuestion tool_use; the chat keeps a collapsed record of it.
// Answering happens in the prompt banner above the input (= driven by the
// terminal screen, not reproducible here), so this bubble only has to show the
// question and its options once expanded.

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
    // Collapsed by default; expanding reveals the full question and the options.
    await bubble.locator('summary').click()
    await expect(bubble.locator('[data-testid=ask-user-question-text]')).toContainText('Which color')
    await expect(bubble.locator('.ask-option-label')).toHaveText(['1. Red', '2. Blue'])
  })
})
