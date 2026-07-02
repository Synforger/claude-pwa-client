// 翻訳 helper (= t(key, vars))。 useSyncExternalStore で state/locale の lang 変化に追随して
// 呼び出し側の component が再 render する。 未定義 key は fallback として key 自体を返す
// (= 開発時に「翻訳もれ」 を目視で発見できる仕組み)。 {var} placeholder は vars で埋める。
import { useSyncExternalStore } from 'react'
import ja from './ja.json'
import en from './en.json'
import { subscribe, getSnapshot } from '../state/locale.js'

const DICT = { ja, en }

function interpolate(template, vars) {
  if (!vars || typeof template !== 'string') return template
  return template.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? String(vars[k]) : `{${k}}`))
}

/** 現在の lang の翻訳 dict を返す (= module-scope で subscribe 未経由でも使いたい場合の逃げ道)。 */
export function tRaw(key, vars) {
  const lang = getSnapshot().lang
  const value = DICT[lang]?.[key] ?? DICT.ja[key] ?? key
  return interpolate(value, vars)
}

/** React component 内で使う。 lang 変化で再 render される。 */
export function useT() {
  const lang = useSyncExternalStore(subscribe, getSnapshot).lang
  return (key, vars) => {
    const value = DICT[lang]?.[key] ?? DICT.ja[key] ?? key
    return interpolate(value, vars)
  }
}
