import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tsParser from '@typescript-eslint/parser'
import boundaries from 'eslint-plugin-boundaries'
import { defineConfig, globalIgnores } from 'eslint/config'

// v2 配下の hexagonal 層構成 (= ADR-010)。 ports/transport/domain/contracts は W1 で配置済、
// state/registry/features/layout/debug は W2-W3 で増える、 boundaries 定義は今のうちに完備。
const V2_LAYERS = [
  { type: 'domain',     pattern: 'src/domain/**'     },
  { type: 'ports',      pattern: 'src/ports/**'      },
  { type: 'contracts',  pattern: 'src/contracts/**'  },
  { type: 'transport',  pattern: 'src/transport/**'  },
  { type: 'state',      pattern: 'src/state/**'      },
  { type: 'registry',   pattern: 'src/registry/**'   },
  { type: 'features',   pattern: 'src/features/**'   },
  { type: 'layout',     pattern: 'src/layout/**'     },
  { type: 'debug',      pattern: 'src/debug/**'      },
]

// import direction (= 矢印は from → allow)。 ADR-010 hexagonal 整合。
// domain (= 純粋 TS) は何にも依存しない、 ports は domain/contracts のみ、 transport が ports
// 経由で実装、 features は ports/state/contracts に依存、 layout は features/state に依存、
// registry は features 配線、 debug は state/transport/ports/contracts を覗く。
const V2_IMPORT_RULES = [
  { from: 'domain',    allow: ['contracts'] },
  { from: 'ports',     allow: ['domain', 'contracts'] },
  { from: 'contracts', allow: [] },
  { from: 'transport', allow: ['ports', 'domain', 'contracts'] },
  { from: 'state',     allow: ['domain', 'contracts'] },
  { from: 'registry',  allow: ['ports', 'domain', 'contracts', 'state'] },
  { from: 'features',  allow: ['ports', 'domain', 'state', 'contracts', 'registry', 'transport'] },
  { from: 'layout',    allow: ['features', 'state'] },
  { from: 'debug',     allow: ['state', 'transport', 'contracts', 'ports'] },
]

// fetch / new WebSocket / new EventSource の直書きを禁止 (= 設計書 02-w1 完了判定、 ADR-010)。
// transport/ 配下のみ例外、 他の v2 配下 file が直接呼ぶと error。
const NO_DIRECT_BACKEND_SYNTAX = [
  { selector: 'CallExpression[callee.name="fetch"]',         message: 'use transport/http.ts apiFetch() instead of fetch()' },
  { selector: 'NewExpression[callee.name="WebSocket"]',      message: 'use transport/ws-pty.ts or ws-views.ts instead of new WebSocket()' },
  { selector: 'NewExpression[callee.name="EventSource"]',    message: 'use transport/sse.ts instead of new EventSource()' },
]

export default defineConfig([
  globalIgnores([
    'dist',
    // cap sync で copy される ipa 内 dist。 lint 対象外。
    'ios/App/App/public',
  ]),

  // 既存 v1 (.js / .jsx) — 既存 lint は無変更
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    rules: {
      'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]' }],
      'react-hooks/set-state-in-effect': 'off',
      'react-refresh/only-export-components': 'off',
    },
  },

  // v2 配下 (.ts / .tsx) — TypeScript parser + react-hooks
  {
    files: ['src/{domain,ports,contracts,transport,state,registry,features,layout,debug}/**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
    ],
    languageOptions: {
      parser: tsParser,
      ecmaVersion: 2020,
      globals: { ...globals.browser, NodeJS: 'readonly' },
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    rules: {
      // TS で type unused は別ルール、 普通の unused-vars は warn (= 開発中の暫定 import 多発を許容)
      'no-unused-vars': 'off',
      // TypeScript の DOM type (= BodyInit, AbortSignal 等) は eslint の no-undef では認識されない、
      // 型存在は tsc が check するので eslint 側は off (= @typescript-eslint 標準推奨)。
      'no-undef': 'off',
    },
  },

  // v2 配下 直書き禁止 (= transport/ 以外で fetch / WebSocket / EventSource 直書きを error、 ADR-010)
  {
    files: ['src/{domain,ports,contracts,state,registry,features,layout,debug}/**/*.{js,jsx,ts,tsx}'],
    rules: {
      'no-restricted-syntax': ['error', ...NO_DIRECT_BACKEND_SYNTAX],
    },
  },

  // v2 配下 silent catch 禁止 (= ADR-012 完了判定 § 3、 frontend 版「except: pass benign 化」 と対称)。
  // `catch {}` や `catch (_) {}` は無自覚な error 握り潰しの温床。 意図的に握る場合は body に
  // ESLint disable コメント or 何らかの説明的 statement を入れる運用にする。
  {
    files: ['src/{domain,ports,contracts,transport,state,registry,features,layout,debug}/**/*.{js,jsx,ts,tsx}'],
    rules: {
      'no-empty': ['error', { allowEmptyCatch: false }],
    },
  },

  // v2 配下 import direction 強制 (= eslint-plugin-boundaries、 ADR-010)
  {
    files: ['src/{domain,ports,contracts,transport,state,registry,features,layout,debug}/**/*.{js,jsx,ts,tsx}'],
    plugins: { boundaries },
    settings: {
      'boundaries/elements': V2_LAYERS,
      'boundaries/include': ['src/**/*'],
    },
    rules: {
      'boundaries/element-types': ['error', { default: 'disallow', rules: V2_IMPORT_RULES }],
    },
  },
])
