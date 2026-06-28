// W2 完成判定 contract: lazy 対象 component が features/*/index.js から static import されてないこと。
//
// 背景: ADR-010 self-register と docs/extending.md (c) lazy chunk 分割は両立する設計だが、 配線 entry
// (= features/<x>/index.js) が lazy 対象 component を static import すると vite が dynamic import を
// 相殺し INEFFECTIVE_DYNAMIC_IMPORT 警告を出して chunk 分離が壊れる。 過去にこの構造で main bundle が
// 33kB+ 膨らんでいた (= 2026-06-29 修正)、 grep 構造 gate で再発防止する。
//
// 対象 = AppShell.jsx (= layout 中央) の `lazy(() => import('../features/<x>/<Name>.jsx'))` 表現で参照される
// component path 群。 lazy 対象でない常時 mount component (= MessageItem / ChatInput / StatusBar / Terminal /
// PlanApprovalBubble 等) は本 contract の対象外 (= entry が tree-shake 防止で touch import するのは OK)。

import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const FEATURES_DIR = join(HERE, '..')          // frontend/src/features/
const APP_SHELL = join(HERE, '..', '..', 'layout', 'AppShell.jsx')

// AppShell.jsx の lazy(...) 内 import path を解析して「lazy 対象 component path」 一覧を作る。
// 例: `lazy(() => import('../features/file-tree/FileTreePanel.jsx'))` → `features/file-tree/FileTreePanel.jsx`
function extractLazyTargets() {
  const src = readFileSync(APP_SHELL, 'utf8')
  const re = /lazy\(\s*\(\s*\)\s*=>\s*import\(\s*['"]\.\.\/features\/([^'"]+)['"]\s*\)\s*\)/g
  const targets = new Set()
  let m
  while ((m = re.exec(src)) !== null) {
    targets.add(m[1])  // e.g. 'file-tree/FileTreePanel.jsx'
  }
  return targets
}

// features/<name>/index.js を読み、 `import './<X>.jsx'` 形式の static import path を列挙する。
function extractStaticJsxImports(indexPath) {
  const src = readFileSync(indexPath, 'utf8')
  const re = /import\s+['"]\.\/([^'"]+\.jsx)['"]/g
  const imports = []
  let m
  while ((m = re.exec(src)) !== null) {
    imports.push(m[1])  // e.g. 'FileTreePanel.jsx'
  }
  return imports
}

describe('W2 chunk-split contract: lazy 対象 component は features index.js から static import されない', () => {
  const lazyTargets = extractLazyTargets()

  it('AppShell.jsx に lazy(() => import(...)) が 1 件以上ある (= 設計書 docs/extending.md (c) chunk 分割)', () => {
    expect(lazyTargets.size).toBeGreaterThan(0)
  })

  const featureDirs = readdirSync(FEATURES_DIR, { withFileTypes: true })
    .filter(d => d.isDirectory() && !d.name.startsWith('_'))
    .map(d => d.name)

  for (const feat of featureDirs) {
    const indexPath = join(FEATURES_DIR, feat, 'index.js')
    if (!existsSync(indexPath)) continue
    const imports = extractStaticJsxImports(indexPath)
    for (const imp of imports) {
      const fullPath = `${feat}/${imp}`
      it(`features/${feat}/index.js は lazy 対象 ${imp} を static import しない`, () => {
        expect(lazyTargets.has(fullPath)).toBe(false)
      })
    }
  }
})
