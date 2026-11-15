// Records which field brings the keyboard up, and whether a Japanese conversion started in it, into the backend's
// record (`sw-log`). Used by AppEffects to catch, on a real phone, the moment the suggestion bar stops appearing:
// the line says which field held the focus, with which attributes, in which container.
//
//   keyboard:focus        a field that takes text got the focus (one line, skipped for a repeat on the same field)
//   keyboard:composition  the focus left it: how many conversions started in it and when the first one did
//
// What the user types is never read: only the field's attributes and sizes, and counts and seconds, are sent.
import { useEffect } from 'react'
import { containerOf } from '../../_common/appUpdate.js'
import { sendSwLog } from './swLog.js'

const FIELD_SELECTOR = 'input, textarea, [contenteditable=""], [contenteditable="true"]'
// Input types that never raise a text keyboard.
const NON_TEXT_INPUT_TYPES = new Set([
  'button', 'checkbox', 'color', 'file', 'image', 'radio', 'range', 'reset', 'submit',
])
const FIELD_ATTRIBUTES = [
  'autocorrect', 'autocomplete', 'spellcheck', 'autocapitalize', 'inputmode', 'enterkeyhint', 'type',
]
const NAME_MAX_LENGTH = 40
const NAME_CLASS_COUNT = 2
// A focus on the same field within this long of the last one writes no `keyboard:focus` line, so a field that is
// tapped again and again does not swell the record.
const REPEAT_FOCUS_WINDOW_MS = 10_000
const MS_PER_TENTH_SECOND = 100

// The field that takes text and holds `target`, or null for a button, a checkbox and the like.
function fieldOf(target) {
  if (!target || typeof target.matches !== 'function' || !target.matches(FIELD_SELECTOR)) return null
  if (target.tagName === 'INPUT' && NON_TEXT_INPUT_TYPES.has((target.type || '').toLowerCase())) return null
  return target
}

// A short name that tells the fields apart in the record: the test id, else the first classes, else the tag.
function nameOf(field) {
  const testId = field.getAttribute('data-testid')
  const classes = typeof field.className === 'string' ? field.className.trim().split(/\s+/).filter(Boolean) : []
  const name = testId || classes.slice(0, NAME_CLASS_COUNT).join('.') || field.tagName.toLowerCase()
  return name.slice(0, NAME_MAX_LENGTH)
}

// What the record keeps of a field: attributes as written (null when absent), and whether it is on the screen.
export function describeField(field) {
  const attributes = {}
  for (const name of FIELD_ATTRIBUTES) attributes[name] = field.getAttribute(name)
  const rect = field.getBoundingClientRect()
  return {
    tag: field.tagName.toLowerCase(),
    name: nameOf(field),
    attributes,
    readonly: !!field.readOnly,
    hasOffsetParent: field.offsetParent !== null,
    width: Math.round(rect.width),
    height: Math.round(rect.height),
  }
}

function tenthsOfSeconds(ms) {
  return Math.round(ms / MS_PER_TENTH_SECOND) / 10
}

// Watches the document's focus and composition events and writes the lines through `send`.
// Returns a function that stops watching. `now` is the clock in milliseconds (injected for tests).
export function watchKeyboard({
  doc = document, win = window, send = sendSwLog, now = () => Date.now(),
} = {}) {
  let focused = null // { field, at, wroteFocusLine, compositionCount, firstCompositionAt }
  let lastFocus = { field: null, at: -Infinity }

  const finish = () => {
    if (!focused) return
    const { field, at, wroteFocusLine, compositionCount, firstCompositionAt } = focused
    focused = null
    if (!wroteFocusLine && compositionCount === 0) return
    send({
      stage: 'keyboard:composition',
      name: nameOf(field),
      compositions: compositionCount,
      firstAfterSec: firstCompositionAt === null ? null : tenthsOfSeconds(firstCompositionAt - at),
      focusSec: tenthsOfSeconds(now() - at),
    })
  }

  const onFocusIn = (event) => {
    finish()
    const field = fieldOf(event.target)
    if (!field) return
    const at = now()
    const isRepeat = lastFocus.field === field && at - lastFocus.at < REPEAT_FOCUS_WINDOW_MS
    lastFocus = { field, at }
    focused = { field, at, wroteFocusLine: !isRepeat, compositionCount: 0, firstCompositionAt: null }
    if (isRepeat) return
    send({
      stage: 'keyboard:focus',
      ...describeField(field),
      container: containerOf(win),
      vvHeight: win.visualViewport ? Math.round(win.visualViewport.height) : null,
      innerHeight: win.innerHeight,
    })
  }

  const onFocusOut = (event) => {
    if (focused && event.target === focused.field) finish()
  }

  const onCompositionStart = (event) => {
    if (!focused || event.target !== focused.field) return
    focused.compositionCount += 1
    if (focused.firstCompositionAt === null) focused.firstCompositionAt = now()
  }

  doc.addEventListener('focusin', onFocusIn, true)
  doc.addEventListener('focusout', onFocusOut, true)
  doc.addEventListener('compositionstart', onCompositionStart, true)
  win.addEventListener('pagehide', finish)
  return () => {
    doc.removeEventListener('focusin', onFocusIn, true)
    doc.removeEventListener('focusout', onFocusOut, true)
    doc.removeEventListener('compositionstart', onCompositionStart, true)
    win.removeEventListener('pagehide', finish)
  }
}

export function useKeyboardLog() {
  useEffect(() => watchKeyboard(), [])
}
