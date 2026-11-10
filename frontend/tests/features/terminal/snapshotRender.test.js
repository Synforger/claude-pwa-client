// @vitest-environment jsdom
// The screen a terminal gets on connect, checked against a real tmux and a real xterm.
//
// For each scenario a tiny Python program (no Claude) draws a screen in a real tmux pane on a private socket;
// `backend.tests.terminal.real_tmux_snapshot` takes the snapshot the backend would send through the same code the
// websocket route runs. The reference is an xterm fed the program's own output. The terminal under test is an xterm
// that held other text, fed the snapshot through createScreenFeed. Every cell (character, width, colours,
// attributes), the cursor position, the active buffer and the cursor's visibility must match.
//
// Skipped when tmux or uv is not installed.

import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect, vi } from 'vitest'
import { Terminal } from '@xterm/xterm'
import { createScreenFeed } from '../../../src/features/terminal/screenFeed.js'

// xterm reads colours through a canvas; jsdom has none and answers null, but prints a notice each time
vi.hoisted(() => {
  HTMLCanvasElement.prototype.getContext = () => null
})

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..')
// tmux and a loaded machine: a scenario took 1.5 s on a quiet one; a load average near 100 is common here
const SCENARIO_TIMEOUT_MS = 90_000

function available(command, args) {
  try {
    execFileSync(command, args, { stdio: 'ignore' })
    return true
  } catch {
    return false
  }
}

const hasTools = available('tmux', ['-V']) && available('uv', ['--version'])

function runScenario(name) {
  const output = execFileSync(
    'uv', ['run', 'python', '-m', 'backend.tests.terminal.real_tmux_snapshot', name],
    { cwd: REPO_ROOT, encoding: 'utf8', timeout: SCENARIO_TIMEOUT_MS },
  )
  return JSON.parse(output.trim().split('\n').pop())
}

const fromHex = (hex) => Uint8Array.from(hex.match(/../g) ?? [], (pair) => parseInt(pair, 16))
const written = (terminal, data) => new Promise((resolve) => terminal.write(data, resolve))

function describeScreen(terminal) {
  const buffer = terminal.buffer.active
  const rows = []
  for (let y = 0; y < terminal.rows; y++) {
    const line = buffer.getLine(buffer.baseY + y)
    const row = []
    for (let x = 0; x < terminal.cols; x++) {
      const cell = line.getCell(x)
      row.push({
        chars: cell.getChars() || ' ',
        width: cell.getWidth(),
        fg: [cell.getFgColorMode(), cell.getFgColor()],
        bg: [cell.getBgColorMode(), cell.getBgColor()],
        bold: cell.isBold(),
        italic: cell.isItalic(),
        dim: cell.isDim(),
        underline: cell.isUnderline(),
        inverse: cell.isInverse(),
        strikethrough: cell.isStrikethrough(),
      })
    }
    rows.push(row)
  }
  return {
    rows,
    cursor: [buffer.cursorX, buffer.cursorY],
    bufferType: buffer.type,
    // xterm has no public getter for a hidden cursor
    cursorHidden: terminal._core.coreService.isCursorHidden,
  }
}

describe.skipIf(!hasTools)('the connect snapshot painted on xterm', () => {
  for (const name of ['colors', 'alternate', 'framed']) {
    it(`${name}: matches the program's own screen cell for cell`, async () => {
      const scenario = runScenario(name)
      const size = { cols: scenario.cols, rows: scenario.rows, allowProposedApi: true }

      const reference = new Terminal(size)
      await written(reference, fromHex(scenario.program_hex))

      // a terminal that already shows something else, as one that reconnects does
      const terminal = new Terminal(size)
      await written(terminal, '\x1b[41mold screen that must not survive\x1b[0m\r\nsecond old line')
      const feed = createScreenFeed({ terminal, sendKeys: () => { throw new Error('no repaint was asked for') } })
      const snapshot = fromHex(scenario.snapshot_hex)
      feed.handleMessage(snapshot.buffer.slice(snapshot.byteOffset, snapshot.byteOffset + snapshot.byteLength))
      await written(terminal, '')

      const expected = describeScreen(reference)
      const actual = describeScreen(terminal)
      expect(typeof actual.cursorHidden).toBe('boolean')
      expect(actual.bufferType).toBe(expected.bufferType)
      expect(actual.cursor).toEqual(expected.cursor)
      expect(actual.cursorHidden).toBe(expected.cursorHidden)
      expect(actual.rows).toEqual(expected.rows)
    }, SCENARIO_TIMEOUT_MS + 10_000)
  }
})
