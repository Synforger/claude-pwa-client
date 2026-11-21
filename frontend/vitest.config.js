import { defineConfig } from 'vitest/config'

import { slowestTestsPlugin } from './testing/slowestTests.js'

// アプリの vite.config.js は config 時に manifest.json を生成する副作用があるため、
// テストはそれを読まない独立 config にする。 全テストは node 環境で完結する
// (= DOM 依存は localStorage 等を in-memory スタブで差し替える方針)。
// A test that runs past TEST_TIMEOUT_MS fails instead of holding the whole run. The limit is three times the slowest
// test of a normal run: 1.43 s (snapshotRender's colors) on 2026-11-21. Measure again with the slowest tests every run
// prints (testing/slowestTests.js) when they change.
const TEST_TIMEOUT_MS = 5_000

export default defineConfig({
  plugins: [slowestTestsPlugin()],
  test: {
    environment: 'node',
    testTimeout: TEST_TIMEOUT_MS,
    include: ['tests/**/*.test.{js,jsx,ts}'],
  },
})
