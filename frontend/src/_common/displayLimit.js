// How many messages the chat list puts in the DOM at once. Its own file so that a test that runs outside the
// browser (the end-to-end scenarios) can read it; src/_common/constants.js reads `import.meta.env` and cannot be
// imported there.
export const DISPLAY_LIMIT = 100
