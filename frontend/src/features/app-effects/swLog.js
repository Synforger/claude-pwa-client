// Sends one diagnostic line to the backend's record (`sw-log`). Called by the hooks in this folder that watch the
// device (viewport, keyboard); a failure to send is dropped, since a diagnostic must never disturb the screen.
import { httpClient } from '../../transport/http.ts'

export function sendSwLog(payload) {
  httpClient.apiFetch('/log/sw', { method: 'POST', jsonBody: payload }).catch(() => {})
}
