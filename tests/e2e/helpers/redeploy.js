// Makes the frontend the test backend serves look like a new build was deployed,
// without building: every hashed file under assets/ gets a new name, everything
// that refers to one is rewritten, and sw.js gets a new shell cache name — which is
// all a client can see of a deploy. `restore()` puts the original build back.
//
// keepOld: true  — the files of the build being replaced stay next to the new ones
//                  (what `npm run build` does: a screen still on the old build can
//                  go on loading its parts)
// keepOld: false — they are gone (a build two deploys old, or a wiped folder)
import { cpSync, existsSync, readdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, extname, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
export const DIST = resolve(__dirname, '..', '..', '..', 'frontend', 'dist')
const BACKUP = `${DIST}.e2e-original`
const TEXT = new Set(['.js', '.css', '.html', '.json'])

function textFiles(dir) {
  const out = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) out.push(...textFiles(path))
    else if (TEXT.has(extname(entry.name))) out.push(path)
  }
  return out
}

export function redeploy(tag, { keepOld = true } = {}) {
  if (!existsSync(BACKUP)) cpSync(DIST, BACKUP, { recursive: true })
  const assets = join(DIST, 'assets')
  const oldNames = readdirSync(assets)
  // A folder under assets/ (the voice parts) is renamed as a whole; the files in it keep their names.
  const renames = new Map(oldNames.map((name) => {
    const ext = extname(name)
    return [name, ext ? `${name.slice(0, -ext.length)}_${tag}${ext}` : `${name}_${tag}`]
  }))
  // New copies first, under their new names, with references pointing at new names.
  for (const [from, to] of renames) cpSync(join(assets, from), join(assets, to), { recursive: true })
  const fresh = new Set(renames.values())
  for (const path of textFiles(DIST)) {
    const inAssets = path.startsWith(assets + sep)
    if (inAssets && !fresh.has(relative(assets, path).split(sep)[0])) continue // an old file stays as it was
    let text = readFileSync(path, 'utf-8')
    for (const [from, to] of renames) text = text.split(from).join(to)
    if (path === join(DIST, 'sw.js')) text = text.replace(/(claude-pwa-shell-[0-9a-zA-Z]+)/, `$1${tag}`)
    writeFileSync(path, text)
  }
  if (!keepOld) for (const name of oldNames) rmSync(join(assets, name), { recursive: true, force: true })
  return { names: renames }
}

export function restoreDeploy() {
  if (!existsSync(BACKUP)) return
  rmSync(DIST, { recursive: true, force: true })
  renameSync(BACKUP, DIST)
}
