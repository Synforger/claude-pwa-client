// 書き出した build を、 配っている folder (= dist) へ載せ替える。
//
// vite が dist へ直に書き出すと、 書き出しの間 (= 実測で約 0.15 秒) は入口の頁が無く、 その前後に
// 「頁は在るが、 指している file がまだ無い」 瞬間が在る。 その間に読んだ画面は壊れる。 また、
// 前の build の file を消してしまうので、 開いたままの古い画面が、 後から読み込む部品を
// 取りに行った時に失敗する。
//
// ここでは、 別の folder (= dist.next) へ書き出した build を次の順で載せる:
//   1. 新しい assets を足す (= 名前に中身の hash が入るので、 前の build の file と衝突しない)
//   2. 入口でない file (= アイコン、 manifest など) を置き換える
//   3. 入口の頁 (= index.html)、 続けて sw.js を置き換える (= どちらも 1 回の rename)
//   4. 今の build と 1 つ前の build のどちらも使っていない assets を消す
// 1 が済んでから 3 を行うので、 どの瞬間に読んでも、 入口の頁が指す file は必ず在る。
// 1 つ前の build の assets は残るので、 古い画面はその部品を読み続けられる
// (= 新しい build へは utils/appUpdate.js の更新の確かめで移る)。
import {
  copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, statSync, writeFileSync,
} from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

// 入口の file。 この順で、 最後に置き換える (= 頁が先。 sw.js が変わると画面が読み込み直すので、
// その時には新しい頁が在る)。
const ENTRY_FILES = ['index.html', 'sw.js']
const ASSETS_DIR = 'assets'
// 直前までの build が使っていた assets の一覧の置き場 (= dist の外。 配らない)。
const GENERATIONS_FILE = '.dist-generations.json'

function listFiles(root, dir = root) {
  const out = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) out.push(...listFiles(root, path))
    else out.push(relative(root, path))
  }
  return out
}

// 同じ folder の中で書いてから rename する (= 読む側には、 古い中身か新しい中身のどちらかだけが見える)。
function replaceFile(from, to) {
  mkdirSync(dirname(to), { recursive: true })
  const tmp = `${to}.publishing`
  copyFileSync(from, tmp)
  renameSync(tmp, to)
}

// 記録 = { current: 今の build の assets, previous: その 1 つ前の build の assets }
function readGenerations(path) {
  try {
    const data = JSON.parse(readFileSync(path, 'utf-8'))
    if (Array.isArray(data.current)) {
      return { current: data.current, previous: Array.isArray(data.previous) ? data.previous : [] }
    }
  } catch { /* 記録が無い / 読めない */ }
  return null
}

const sameSet = (a, b) => a.length === b.length && a.every((x) => b.includes(x))

// nextDir の build を distDir へ載せる。 返り値 = { added, removed } (= assets の増減)。
export function publishDist(nextDir, distDir, { generationsPath = join(dirname(distDir), GENERATIONS_FILE) } = {}) {
  if (!existsSync(join(nextDir, 'index.html'))) {
    throw new Error(`no build to publish at ${nextDir} (index.html missing)`)
  }
  const nextFiles = listFiles(nextDir)
  const isAsset = (f) => f.split(/[\\/]/)[0] === ASSETS_DIR
  const nextAssets = nextFiles.filter(isAsset)
  // 1 つ前の build の assets。
  //   - 記録が無い (= この仕組みを入れる前に作られた dist): 今 dist に在る assets 全部を前の build の物として扱う
  //   - 同じ build の載せ直し (= 中身が変わっていない): 世代を進めない (= 進めると、 載せ直すだけで
  //     1 つ前の build の file が消える)
  //   - それ以外: 今までの build が 1 つ前になる
  const distAssetsDir = join(distDir, ASSETS_DIR)
  const onDisk = existsSync(distAssetsDir) ? listFiles(distDir).filter(isAsset) : []
  const recorded = readGenerations(generationsPath)
  const previous = !recorded
    ? onDisk
    : sameSet(recorded.current, nextAssets) ? recorded.previous : recorded.current

  mkdirSync(distDir, { recursive: true })
  // 1. 新しい assets を足す
  let added = 0
  for (const f of nextAssets) {
    const to = join(distDir, f)
    if (existsSync(to) && statSync(to).size === statSync(join(nextDir, f)).size) continue
    replaceFile(join(nextDir, f), to)
    added += 1
  }
  // 2. 入口でない file を置き換える
  const others = nextFiles.filter((f) => !isAsset(f) && !ENTRY_FILES.includes(f))
  for (const f of others) replaceFile(join(nextDir, f), join(distDir, f))
  // 3. 入口を置き換える
  for (const f of ENTRY_FILES) {
    if (existsSync(join(nextDir, f))) replaceFile(join(nextDir, f), join(distDir, f))
  }
  // 4. 今の build も 1 つ前の build も使っていない物を消す
  const keep = new Set([...nextAssets, ...previous])
  let removed = 0
  for (const f of existsSync(distAssetsDir) ? listFiles(distDir).filter(isAsset) : []) {
    if (keep.has(f)) continue
    rmSync(join(distDir, f), { force: true })
    removed += 1
  }
  const nextTop = new Set(nextFiles.filter((f) => !isAsset(f)))
  for (const f of listFiles(distDir).filter((x) => !isAsset(x))) {
    if (!nextTop.has(f)) { rmSync(join(distDir, f), { force: true }); removed += 1 }
  }
  writeFileSync(generationsPath, JSON.stringify({ current: nextAssets, previous }, null, 2))
  rmSync(nextDir, { recursive: true, force: true })
  return { added, removed }
}

// `node build/publishDist.js` (= npm run build の後段)
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
  const { added, removed } = publishDist(join(root, 'dist.next'), join(root, 'dist'))
  console.log(`published dist: ${added} asset(s) added, ${removed} file(s) from older builds removed`)
}
