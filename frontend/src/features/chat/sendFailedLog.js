// Writes one line to the backend's record (`sw-log`, stage `send:failed`) each time a sent bubble is marked "Not
// delivered", with why: the HTTP status or error of the send, the backend's reason, and how long the send took. The
// mark is shown on the screen only, so without this line nothing tells afterwards which way it came. Called by
// `useChatStream`; a failure to write is dropped, since a diagnostic must never disturb the screen.
import { apiFetch } from '../../_common/api.js'

export function logSendFailed(sid, detail) {
  apiFetch('/log/sw', { method: 'POST', jsonBody: { stage: 'send:failed', sid, ...detail } }).catch(() => {})
}
