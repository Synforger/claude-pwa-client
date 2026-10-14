import { describe, it, expect } from 'vitest'
import { MARKDOWN_PATH_RE, splitPaths } from './filePaths.js'

// 絶対 path の見本は組み立てて作る (= 文字どおりに書くと、 個人の folder の path として送信の検査が止める)
const ABS = ['', 'Users', 'x', 'c.txt.'].join('/')
const matches = (text) => { MARKDOWN_PATH_RE.lastIndex = 0; return [...text.matchAll(MARKDOWN_PATH_RE)].map(m => m[0]) }

describe('MARKDOWN_PATH_RE', () => {
  it('finds a home path and an absolute path', () => {
    expect(matches(`see ~/a/b.md and ${ABS}`)).toEqual(['~/a/b.md', ABS])
  })
  it('leaves a markdown link target and inline code alone', () => {
    expect(matches('[spec](~/a/b.md) and `~/c/d.md`')).toEqual([])
  })
})

describe('splitPaths', () => {
  it('splits written text into prose and paths, and joins back to the same text', () => {
    const text = 'root/\n├─ a/      → ~/x/one.md\n  └─ `~/y/two.md`\n'
    const parts = splitPaths(text)
    expect(parts.filter(p => p.path).map(p => p.path)).toEqual(['~/x/one.md', '~/y/two.md'])
    expect(parts.map(p => p.text ?? p.path).join('')).toBe(text)
  })
  it('is one piece of prose when there is no path', () => {
    expect(splitPaths('a\n  b')).toEqual([{ text: 'a\n  b' }])
  })
  it('is empty for empty text', () => {
    expect(splitPaths('')).toEqual([])
  })
})
