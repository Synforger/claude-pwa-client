// W2 完成判定 contract: lazy 対象 component が配線 entry (= features/*/index.js) から static import されてないこと。
//
// 背景: ADR-010 self-register と docs/architecture/extending.md (c) lazy chunk 分割は両立する設計だが、 配線 entry
// (= features/<x>/index.js) が lazy 対象 component を static import すると vite が dynamic import を
// 相殺し INEFFECTIVE_DYNAMIC_IMPORT 警告を出して chunk 分離が壊れる。 過去にこの構造で main bundle が
// 33kB+ 膨らんでいた (= 2026-06-29 修正)、 grep 構造 gate で再発防止する。
//
// W2 Phase E2 (= 2026-06-29 移行完了): 全 7 overlay が registerOverlay の Component spec に
// 移行済 (= FilePreviewModal / FileTreePanel / FavoritesQuickPicker / MoonlightFrame + drawer /
// subagents / tasks)。 W2 Phase F-4 + F-6 (= 2026-06-29): dialogs 3 件 (= confirmDelete /
// confirmEnd / confirmStop) も追加で Component spec 経由化、 旧 AppShell.jsx は完全削除されて
// Layout.jsx 体制に移行。 本 contract は features/<x>/index.js の Component spec 経路 (= b) のみ gate。
//
// 旧 経路 (a) = AppShell.jsx の `lazy(() => import('../features/<x>/<X>.jsx'))` は AppShell.jsx
// 退役と同時に消滅 (= 旧 contract の lazy 件数 0 確認は AppShell 存在前提で書かれていたので、
// AppShell 削除確認 + Layout.jsx に lazy() が出現しないことの確認に置換した)。
//
// lazy 対象でない常時 mount component (= MessageItem / ChatInput / StatusBar / Terminal / PlanApprovalBubble
// 等) は本 contract の対象外 (= entry が tree-shake 防止で touch import するのは OK)。

import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const FEATURES_DIR = join(HERE, '..')          // frontend/src/features/
const LAYOUT_DIR = join(HERE, '..', '..', 'layout')
const APP_SHELL = join(LAYOUT_DIR, 'AppShell.jsx')
const LAYOUT_JSX = join(LAYOUT_DIR, 'Layout.jsx')

// Layout.jsx の lazy(...) 内 import path を解析して「lazy 対象 component path」 一覧を作る
// (= W2 Phase F-6 切替後の起点。 旧 AppShell.jsx は削除済、 Layout には lazy() が一切出ない設計)。
function extractLazyTargets() {
  const src = readFileSync(LAYOUT_JSX, 'utf8')
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

// features/<name>/index.js の register 内 `Component: () => import('./<X>.jsx')` spec を列挙する
// (= W2 Phase E1)。 OverlayHost が React.lazy で wrap する経路。
function extractComponentSpecs(indexPath) {
  const src = readFileSync(indexPath, 'utf8')
  const re = /Component\s*:\s*\(\s*\)\s*=>\s*import\(\s*['"]\.\/([^'"]+\.jsx)['"]\s*\)/g
  const specs = []
  let m
  while ((m = re.exec(src)) !== null) {
    specs.push(m[1])  // e.g. 'FilePreviewModal.jsx'
  }
  return specs
}

describe('W2 chunk-split contract: lazy 対象 component は features index.js から static import されない', () => {
  const lazyTargets = extractLazyTargets()

  it('layout/AppShell.jsx は削除済 (= W2 Phase F-6 完成判定、 Layout.jsx 体制に完全移行)', () => {
    expect(existsSync(APP_SHELL)).toBe(false)
  })

  it('Layout.jsx の lazy(() => import(...)) は 0 件 (= 全 overlay が Component spec 経由)', () => {
    expect(lazyTargets.size).toBe(0)
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
      it(`features/${feat}/index.js は Layout lazy 対象 ${imp} を static import しない`, () => {
        expect(lazyTargets.has(fullPath)).toBe(false)
      })
    }
  }
})

describe('W2 Phase E1 chunk-split contract: overlayRegistry Component spec は同 index.js から static import されない', () => {
  const featureDirs = readdirSync(FEATURES_DIR, { withFileTypes: true })
    .filter(d => d.isDirectory() && !d.name.startsWith('_'))
    .map(d => d.name)

  let totalSpecs = 0
  for (const feat of featureDirs) {
    const indexPath = join(FEATURES_DIR, feat, 'index.js')
    if (!existsSync(indexPath)) continue
    const specs = extractComponentSpecs(indexPath)
    totalSpecs += specs.length
    const staticImports = new Set(extractStaticJsxImports(indexPath))
    for (const spec of specs) {
      it(`features/${feat}/index.js は Component spec ${spec} を同 file で static import しない`, () => {
        expect(staticImports.has(spec)).toBe(false)
      })
    }
  }

  it('Component spec を持つ entry が 10 件 (= E-1 で 4 件 + E-2 で 3 件 + F-4 で confirmDelete 1 件 + F-4 残で confirmEnd / confirmStop 2 件追加)', () => {
    expect(totalSpecs).toBe(10)
  })
})
