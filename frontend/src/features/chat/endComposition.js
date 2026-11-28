// Ends a Japanese (or other IME) conversion that is still open in a field, before the screen replaces the field's
// text. Called by ChatInput when a message is sent. WebKit keeps the conversion open in its own state when a script
// replaces the text under it, and from then on the keyboard of that page shows no candidates until the page is
// opened again. Taking the focus off the field ends the conversion the ordinary way; the focus is given back at once,
// inside the same tap, so the keyboard stays up.

// Ends the open conversion in `field` and gives the focus back. Returns whether there was one to end.
export function endComposition(field, isComposing, doc = document) {
  if (!field || !isComposing || doc.activeElement !== field) return false
  field.blur()
  field.focus({ preventScroll: true })
  return true
}
