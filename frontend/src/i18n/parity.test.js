// i18n の構造検査 (= 2026-07-06 手動棚卸しの機械化):
//   1. en / ja のキー集合が完全一致 (= 片言語だけの追加漏れを CI で即検知)
//   2. コードが静的に参照する全キーが両言語に存在
// 動的キー (= `backend.${code}` / labelKey table 経由) は静的抽出に乗らないので
// 「使用 ⊆ 定義」 方向のみ検査する (= 未使用キーの死活判定は人力、 動的参照が
// 機械では区別できないため)。
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const en = JSON.parse(fs.readFileSync(path.join(here, 'en.json'), 'utf-8'))
const ja = JSON.parse(fs.readFileSync(path.join(here, 'ja.json'), 'utf-8'))

function collectUsedKeys(dir) {
  const used = new Set()
  const walk = (d) => {
    for (const ent of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, ent.name)
      if (ent.isDirectory()) { walk(p); continue }
      if (!/\.(jsx?|tsx?)$/.test(ent.name) || ent.name.includes('.test.')) continue
      const src = fs.readFileSync(p, 'utf-8')
      for (const m of src.matchAll(/\bt(?:Raw)?\(\s*['"]([a-z0-9_.]+)['"]/g)) {
        used.add(m[1])
      }
      // labelKey table 形式 (= MessageItem の stop_reason map 等) も拾う
      for (const m of src.matchAll(/labelKey:\s*['"]([a-z0-9_.]+)['"]/g)) {
        used.add(m[1])
      }
    }
  }
  walk(dir)
  return used
}

describe('i18n parity', () => {
  it('en と ja のキー集合が一致する', () => {
    const onlyEn = Object.keys(en).filter(k => !(k in ja))
    const onlyJa = Object.keys(ja).filter(k => !(k in en))
    expect(onlyEn).toEqual([])
    expect(onlyJa).toEqual([])
  })

  it('コードが参照する全キーが定義されている', () => {
    const used = collectUsedKeys(path.join(here, '..'))
    const missing = [...used].filter(k => !(k in en))
    expect(missing).toEqual([])
  })
})
