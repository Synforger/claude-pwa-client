// 票の絵 (= 統合 stream の `tickets` channel) を受けて state/tickets.js に写す hook。 画面で 1 回だけ置く (= AppEffects)。

import { useEffect } from 'react'
import { ticketsSse } from '../../transport/select.ts'
import { applyTicketsSnapshot } from '../../state/tickets.js'

export function useTicketsChannel() {
  useEffect(() => ticketsSse.subscribe(applyTicketsSnapshot), [])
}
