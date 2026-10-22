import { defineConfig } from 'vitest/config'

// アプリの vite.config.js は config 時に manifest.json を生成する副作用があるため、
// テストはそれを読まない独立 config にする。 全テストは node 環境で完結する
// (= DOM 依存は localStorage 等を in-memory スタブで差し替える方針)。
// A test that renders a long note or runs the voice model's feature extraction took 5.4–6.6 s on a busy
// machine (load average near 40), past vitest's default 5 s. Every test gets three times that.
const TEST_TIMEOUT_MS = 20_000

export default defineConfig({
  test: {
    environment: 'node',
    testTimeout: TEST_TIMEOUT_MS,
    include: ['tests/**/*.test.{js,jsx}'],
  },
})
