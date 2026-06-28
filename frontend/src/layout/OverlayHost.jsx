// overlayRegistry を走査して open 中 overlay を lazy + Suspense + LazyBoundary で 1 経路 render する
// 中央 host (= W2 Phase E1)。 AppShell.jsx は本 component を 1 行配置するだけで、 個別 overlay の
// `lazy(() => import(...))` / Suspense / LazyBoundary / props 渡しを持たない (= ADR-010 中央非依存)。
//
// 移行期混在 OK の設計: Component spec を持たない registry entry (= drawer / subagents / tasks の
// 3 件、 E-2 で移行予定) は OverlayHost が skip し、 AppShell.jsx 側の従来 lazy render block が
// 引き続き効く。 E-1 では FilePreviewModal / FileTreePanel / FavoritesQuickPicker / MoonlightFrame
// の 4 件だけが本 host 経由で render される。
//
// 各 overlay は **props 自己解決契約**で、 OverlayHost は props 渡しを一切しない。 各 component が
// 内部で state/ui.js を subscribe して own state を pull、 close は setOverlay 直呼出。
//
// LazyBoundary は AppShell.jsx から移送 (= F-60 互換、 chunk fetch 失敗時に該当 modal だけ閉じる)。

import { lazy, Suspense, Component, useMemo, useSyncExternalStore } from 'react'
import { list, describe } from '../registry/overlayRegistry.js'
import { subscribe as subscribeUi, getSnapshot as getUiSnapshot } from '../state/ui.js'

// F-60 (= 2026-06-21): lazy modal の chunk fetch が失敗した時の最小 ErrorBoundary。
// 失敗した modal だけ閉じる + 軽い update 促し で留め、 ユーザの裏で動いてる chat / streaming
// を生存させる方針 (= AppShell.jsx から物理移送、 改変なし)。
class LazyBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false }
  }
  static getDerivedStateFromError() { return { hasError: true } }
  componentDidCatch(error, info) { console.error('[LazyBoundary]', error, info) }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(0,0,0,0.6)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 9999,
        }}>
          <div style={{
            background: '#1a1a1a',
            color: '#ccc',
            padding: '20px 24px',
            borderRadius: 8,
            border: '1px solid #444',
            maxWidth: 320,
            textAlign: 'center',
            fontSize: 13,
            lineHeight: 1.5,
          }}>
            <p style={{ margin: '0 0 14px' }}>画面の読込に失敗しました</p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
              <button
                type="button"
                onClick={() => this.setState({ hasError: false })}
                style={{
                  padding: '6px 14px',
                  background: '#2a2a2a',
                  color: '#ccc',
                  border: '1px solid #444',
                  borderRadius: 4,
                  cursor: 'pointer',
                  fontSize: 13,
                }}
              >閉じる</button>
              <button
                type="button"
                onClick={() => window.location.reload()}
                style={{
                  padding: '6px 14px',
                  background: '#3a5a8c',
                  color: '#fff',
                  border: '1px solid #4a6a9c',
                  borderRadius: 4,
                  cursor: 'pointer',
                  fontSize: 13,
                }}
              >↺ アプリ更新</button>
            </div>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

// registry の Component spec を React.lazy で wrap した結果を name→Lazy で cache。
// React.lazy は同 import factory を毎回 new Lazy する設計上避けるべきなので module-level cache 必須。
// describe(name) は features/*/index.js が起動時 self-register した結果を返すので、 module load
// 順 (= App.jsx → '../features/*/index.js' import → register call) で確定する。
const LAZIES = new Map()
function getLazy(name) {
  if (!LAZIES.has(name)) {
    const entry = describe(name)
    LAZIES.set(name, entry?.Component ? lazy(entry.Component) : null)
  }
  return LAZIES.get(name)
}

export default function OverlayHost() {
  // ui.overlays.* を subscribe して open 中の overlay を判定。 single subscribe で全 overlay の
  // open 状態を見るので、 上流の setOverlay 1 件で本 host 1 回再 render (= 個別 subscribe より軽い)。
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  // overlayRegistry の登録名は起動時 self-register で確定、 module load 後は不変なので mount 時固定。
  const names = useMemo(() => list(), [])
  return (
    <>
      {names.map(name => {
        const Lazy = getLazy(name)
        if (!Lazy) return null  // Component spec 未登録 = AppShell 側 render (= 移行期混在 OK)
        const open = ui.overlays[name]
        if (!open) return null  // truthy check で十分 (= string / boolean / null/false で網羅)
        return (
          <LazyBoundary key={name}>
            <Suspense fallback={null}>
              <Lazy />
            </Suspense>
          </LazyBoundary>
        )
      })}
    </>
  )
}
