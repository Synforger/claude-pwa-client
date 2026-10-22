// localStorage を JSON 値として安全に読み書きするヘルパ。 quota 超過 / private mode /
// 壊れた値での例外を握りつぶし、 各所に散っていた try/catch + JSON.parse 定型を集約する。
// 生文字列フラグ (= '1' 等) を扱う箇所は対象外 (= 直接 localStorage を使う)。

export function lsGet(key, fallback = null) {
  try {
    const raw = localStorage.getItem(key)
    if (raw == null) return fallback
    return JSON.parse(raw)
  } catch {
    return fallback
  }
}

export function lsSet(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch { /* quota 超過 / private mode は黙って無視 */ }
}

export function lsRemove(key) {
  try { localStorage.removeItem(key) } catch { /* ignore */ }
}

// --- debounced setter (= F-46) ---------------------------------------------
//
// 「同じ key への write が短時間に連発する」 ケースで、 末尾値だけ commit する。
// 11 箇所散在していた localStorage write の規律を 1 ヘルパに揃える。
//
//   - 同 key への連続 lsSetDebounced は最後の value だけ書く (= 中間 value は捨てる)
//   - 既定 500ms。 呼出側が delay を明示すれば上書き
//   - lsFlushDebounced(key?) で待ち中の write を即時 commit (= 全 key 一括 or 単独)
//   - pagehide / beforeunload では自動 flush (= タブ閉じで未 commit を失わない)
//
// 注意: state を 1 か所に持つので test では `__lsResetDebounced()` (= 後述) でクリア。

const debouncePending = new Map() // key -> { timer, value }

function commitNow(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch { /* quota / private mode は黙って無視 (= lsSet と同方針) */ }
}

export function lsSetDebounced(key, value, delay = 500) {
  const cur = debouncePending.get(key)
  if (cur && cur.timer) clearTimeout(cur.timer)
  const timer = setTimeout(() => {
    const entry = debouncePending.get(key)
    if (!entry) return
    debouncePending.delete(key)
    commitNow(key, entry.value)
  }, delay)
  debouncePending.set(key, { timer, value })
}

export function lsFlushDebounced(key) {
  if (key !== undefined) {
    const entry = debouncePending.get(key)
    if (!entry) return
    if (entry.timer) clearTimeout(entry.timer)
    debouncePending.delete(key)
    commitNow(key, entry.value)
    return
  }
  // 全 key flush
  for (const [k, entry] of Array.from(debouncePending.entries())) {
    if (entry.timer) clearTimeout(entry.timer)
    commitNow(k, entry.value)
  }
  debouncePending.clear()
}

// test 用: pending を全部破棄 (= commit しない)。 export 名に `__` prefix を付けて
// production code から呼ばない目印。
export function __lsResetDebounced() {
  for (const entry of debouncePending.values()) {
    if (entry.timer) clearTimeout(entry.timer)
  }
  debouncePending.clear()
}

// タブ閉じ / アンロード時に未 commit を救う。 module load 時 1 回だけ install。
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  const flushAll = () => { try { lsFlushDebounced() } catch { /* ignore */ } }
  // pagehide は iOS Safari でも信頼できる (= BFCache 対応)。 beforeunload は補助。
  window.addEventListener('pagehide', flushAll)
  window.addEventListener('beforeunload', flushAll)
}
