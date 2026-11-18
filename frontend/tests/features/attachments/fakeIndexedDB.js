// A small in-memory stand-in for the part of IndexedDB that imageStore.js uses (open, one object store with put, get,
// delete, getAllKeys and a cursor), so its tests run in the node environment. Requests answer on a microtask, the way
// the real ones answer after the caller has set its handlers.

/** Installs the fake as `globalThis.indexedDB` and returns the records it keeps. `unavailable` makes `open` throw. */
export function installFakeIndexedDB({ unavailable = false } = {}) {
  const records = new Map()

  const request = (run) => {
    const req = { result: undefined, error: null, onsuccess: null, onerror: null }
    queueMicrotask(() => {
      try {
        req.result = run()
        if (req.onsuccess) req.onsuccess({ target: req })
      } catch (error) {
        req.error = error
        if (req.onerror) req.onerror({ target: req })
      }
    })
    return req
  }

  const openCursor = () => {
    const req = { result: null, error: null, onsuccess: null, onerror: null }
    const entries = [...records.entries()]
    let index = 0
    const answer = () => {
      const entry = entries[index]
      req.result = entry
        ? { key: entry[0], value: entry[1], continue: () => { index += 1; queueMicrotask(answer) } }
        : null
      if (req.onsuccess) req.onsuccess({ target: req })
    }
    queueMicrotask(answer)
    return req
  }

  const store = {
    put: (value, key) => request(() => { records.set(key, value); return key }),
    get: (key) => request(() => records.get(key)),
    delete: (key) => request(() => { records.delete(key) }),
    getAllKeys: () => request(() => [...records.keys()]),
    openCursor,
  }
  const database = {
    objectStoreNames: { contains: () => true },
    createObjectStore: () => store,
    transaction: () => ({ objectStore: () => store }),
  }

  globalThis.indexedDB = {
    open: () => {
      if (unavailable) throw new Error('IndexedDB unavailable')
      const req = { result: database, error: null, onsuccess: null, onerror: null, onupgradeneeded: null }
      queueMicrotask(() => { if (req.onsuccess) req.onsuccess({ target: req }) })
      return req
    },
  }
  return records
}
