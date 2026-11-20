// Posts one sent message to the backend's send door, and posts it again when the request itself failed before an answer
// came (the network dropped it, or the wait ran out). A screen that comes back to the front sends on a connection iOS
// closed while it was behind, and that first request fails before it reaches the backend; posting it again a moment
// later goes through. A request can also reach the backend and be typed while iOS cuts off only its answer, when the
// app goes behind right after sending; the repeat then comes once the app is in front again, however late. The same
// `Idempotency-Key` goes with every try, and the backend remembers typed keys without a time limit
// (`backend/terminal/send_dedup.py`), so it types a message at most once and answers a repeat with `deduped`. An HTTP answer, whatever its status, is returned as it is: only a request that got
// no answer is tried again. Called by `useChatStream` for the text and the attachment doors.
import { apiFetch } from '../../_common/api.js'

// The waits before the second and the third try. The first lets iOS bring the network back after the page comes to
// the front; the second covers a slower return.
export const RETRY_WAITS_MS = [500, 1500]

const wait = ms => new Promise(resolve => setTimeout(resolve, ms))

// → the Response of the last try; throws the error of the last try when none got an answer. `tries` counts them, for
// the record of a send that still failed.
export async function postSend(path, options, { waits = RETRY_WAITS_MS, onTry } = {}) {
  let lastError
  for (let attempt = 0; attempt <= waits.length; attempt++) {
    if (attempt > 0) await wait(waits[attempt - 1])
    onTry?.(attempt + 1)
    try {
      return await apiFetch(path, { ...options, method: 'POST', retry: 0 })
    } catch (error) {
      lastError = error
    }
  }
  throw lastError
}
