// Service Worker のアプリシェル cache 名を build ごとに決める。
//
// sw.js の cache 名は、 画面の bundle が変わるたびに変えないといけない (= 変えないと既存の client が
// 新しい SW を activate せず、 開いたままの画面が消えた chunk を読みに行く)。 手で版を上げる運用は
// 上げ忘れが起きた (= 2026-09-23 v1.4.1) ので、 bundle の file 名 (= 中身の hash 入り) と sw.js 自身の
// 中身から名前を決める。 中身が同じなら名前も同じ (= 無駄な再読込をさせない)。
import { createHash } from 'node:crypto'

export const BUILD_ID_PLACEHOLDER = '__BUILD_ID__'
const BUILD_ID_LENGTH = 12

export function buildIdFor(swSource, bundleFileNames) {
  const hash = createHash('sha256')
  hash.update(swSource)
  for (const name of [...bundleFileNames].sort()) hash.update(`\n${name}`)
  return hash.digest('hex').slice(0, BUILD_ID_LENGTH)
}

// 置き場所が無ければ例外 (= 書き換え漏れで古い cache 名のまま出荷しない)。
export function stampServiceWorker(swSource, bundleFileNames) {
  if (!swSource.includes(BUILD_ID_PLACEHOLDER)) {
    throw new Error(`sw.js has no ${BUILD_ID_PLACEHOLDER} placeholder to stamp`)
  }
  const id = buildIdFor(swSource, bundleFileNames)
  return { id, source: swSource.split(BUILD_ID_PLACEHOLDER).join(id) }
}
