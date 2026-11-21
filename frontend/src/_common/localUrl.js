// A URL written for this machine's own address (localhost, 127.0.0.1) made into one the screen's device can open.
// The screen reaches the backend's machine over the tailnet by its name, and `tailscale serve` exposes a local port under
// the same number on that name (the page port, as backend/routes/files.py `_page_target` assumes too). So a link to
// `http://localhost:<port>/<path>` is opened as `<the screen's scheme>://<the screen's host>:<port>/<path>`.
// Pure: the location comes in. Read by the chat's Markdown links (features/chat/MessageRenderer.jsx).

const LOCAL_URL = /^https?:\/\/(?:localhost|127\.0\.0\.1)(:\d+)?(\/[^\s]*)?$/i
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1'])

/** `url` as the device showing the screen opens it: unchanged unless it names this machine's own address and the screen
 * itself is not opened on that address (on the machine itself, localhost works as written). */
export function onScreenHost(url, location) {
  if (typeof url !== 'string' || !location || LOCAL_HOSTS.has(location.hostname)) return url
  const found = LOCAL_URL.exec(url)
  if (!found) return url
  return `${location.protocol}//${location.hostname}${found[1] || ''}${found[2] || ''}`
}
