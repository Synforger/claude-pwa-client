import { rmSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const RUNTIME = resolve(__dirname, '..', 'fixtures', '_runtime')

export default async function globalTeardown() {
  // Wipe the tmp data tree the launcher created. CPC_E2E_KEEP_RUNTIME=1 lets
  // a flaky scenario leave forensic state behind for inspection.
  if (process.env.CPC_E2E_KEEP_RUNTIME === '1') return
  rmSync(RUNTIME, { recursive: true, force: true })
}
