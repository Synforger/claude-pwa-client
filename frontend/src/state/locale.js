// UI 言語切替 store (2026-07-02 追加)。 lang = 'ja' | 'en'。 store を購読して useSyncExternalStore
// 経由でコンポーネントが再 render する。 localStorage 永続化、 初回起動時は navigator.language を
// 見て自動判定 (ja*: 日本語、 それ以外: 英語)。 backend 由来の文字列 (エラーメッセージ / status 等)
// は本 store の対象外、 英語モードでも日本語のまま出す (= 別途対応の余地を残す)。
import { createStore } from './_store.js'

const LS_KEY = 'cpc_v2_locale'

function detectInitialLang() {
  try {
    const stored = localStorage.getItem(LS_KEY)
    if (stored === 'ja' || stored === 'en') return stored
  } catch { /* localStorage 不可 (= SSR / private mode 等) */ }
  const navLang = (typeof navigator !== 'undefined' && navigator.language) || ''
  return navLang.toLowerCase().startsWith('ja') ? 'ja' : 'en'
}

const INITIAL = { lang: detectInitialLang() }
const store = createStore(INITIAL, { name: 'locale' })

export const getSnapshot = () => store.getSnapshot()
export const subscribe = (listener) => store.subscribe(listener)

export function setLang(lang) {
  const normalized = lang === 'ja' ? 'ja' : 'en'
  store.setState(prev => (prev.lang === normalized ? prev : { ...prev, lang: normalized }))
  try { localStorage.setItem(LS_KEY, normalized) } catch { /* ignore */ }
}

export function getLang() {
  return store.getSnapshot().lang
}
