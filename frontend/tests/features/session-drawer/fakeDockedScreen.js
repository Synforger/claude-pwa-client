// Stand-ins for the browser's matchMedia and localStorage in the tests of the docked tab list: the screen has one query,
// whose answer the test flips, and the storage lives in memory (as in tests/_common/storage.test.js, since the
// jsdom of this runner has none that works).
// It is a helper, not a test (the name has no `.test`), so the runner does not collect it.
import { vi } from 'vitest'

export function installFakeStorage() {
  let store = {}
  vi.stubGlobal('localStorage', {
    getItem: (key) => (key in store ? store[key] : null),
    setItem: (key, value) => { store[key] = String(value) },
    removeItem: (key) => { delete store[key] },
    clear: () => { store = {} },
  })
}

export function installFakeScreen(initialMatches) {
  let matches = initialMatches
  const listeners = new Set()
  const asked = []
  window.matchMedia = vi.fn((query) => {
    asked.push(query)
    return {
      get matches() { return matches },
      media: query,
      addEventListener: (type, listener) => { if (type === 'change') listeners.add(listener) },
      removeEventListener: (type, listener) => { if (type === 'change') listeners.delete(listener) },
    }
  })
  return {
    asked,
    listenerCount: () => listeners.size,
    // Make the screen wide / narrow and tell whoever listens (the caller wraps this in act()).
    set(next) {
      matches = next
      for (const listener of [...listeners]) listener({ matches: next })
    },
  }
}

export function removeFakeScreen() {
  delete window.matchMedia
}
