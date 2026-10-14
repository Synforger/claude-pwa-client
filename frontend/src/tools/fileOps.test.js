import { describe, it, expect } from 'vitest'
import { formatTool } from '../utils/format.js'
import { SHORT_LABEL_MAX } from './_shared.js'

// Bash の行は、 畳んだ見出し (= shortLabel) と、 開いた時に出る全文 (= label) を別に持つ。
// claude は Bash の呼び出しに「何をするか」 の 1 行 (= input.description) を付けるので、
// 見出しはそれを出し、 コマンドは開いた時に読める形にする。

const bash = (input) => formatTool({ id: 't1', name: 'Bash', input })

describe('Bash の行', () => {
  it('説明文が在れば、 見出しは説明文で、 開いた中はコマンド', () => {
    const tool = bash({ command: 'git status -sb | head -1', description: 'Show working tree status' })
    expect(tool.shortLabel).toBe('Show working tree status')
    expect(tool.label).toBe('$ git status -sb | head -1')
  })

  it('説明文が無ければ、 見出しはコマンド', () => {
    const tool = bash({ command: 'ls' })
    expect(tool.shortLabel).toBe('$ ls')
    expect(tool.label).toBe('$ ls')
  })

  it('空白だけの説明文は、 無い物として扱う', () => {
    expect(bash({ command: 'ls', description: '   ' }).shortLabel).toBe('$ ls')
  })

  it('文字列でない説明文は、 無い物として扱う', () => {
    expect(bash({ command: 'ls', description: { text: 'x' } }).shortLabel).toBe('$ ls')
  })

  it('長い説明文は、 見出しの上限で切る', () => {
    const tool = bash({ command: 'ls', description: 'a'.repeat(SHORT_LABEL_MAX + 20) })
    expect(tool.shortLabel).toBe('a'.repeat(SHORT_LABEL_MAX) + '…')
  })

  it('説明文の前後の空白と改行は、 見出しに持ち込まない', () => {
    expect(bash({ command: 'ls', description: '  List files\n' }).shortLabel).toBe('List files')
  })
})

describe('説明文を持たないツールの行', () => {
  it('Read の見出しは path のまま', () => {
    const tool = formatTool({ id: 't2', name: 'Read', input: { file_path: '/tmp/a.txt', description: 'ignored' } })
    expect(tool.shortLabel).toBe('read  /tmp/a.txt')
  })
})
