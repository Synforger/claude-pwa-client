import { useState, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python'
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript'
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript'
import jsx from 'react-syntax-highlighter/dist/esm/languages/prism/jsx'
import tsx from 'react-syntax-highlighter/dist/esm/languages/prism/tsx'
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json'
import css from 'react-syntax-highlighter/dist/esm/languages/prism/css'
import scss from 'react-syntax-highlighter/dist/esm/languages/prism/scss'
import sass from 'react-syntax-highlighter/dist/esm/languages/prism/sass'
import less from 'react-syntax-highlighter/dist/esm/languages/prism/less'
import markup from 'react-syntax-highlighter/dist/esm/languages/prism/markup'
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml'
import toml from 'react-syntax-highlighter/dist/esm/languages/prism/toml'
import ini from 'react-syntax-highlighter/dist/esm/languages/prism/ini'
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash'
import batch from 'react-syntax-highlighter/dist/esm/languages/prism/batch'
import powershell from 'react-syntax-highlighter/dist/esm/languages/prism/powershell'
import docker from 'react-syntax-highlighter/dist/esm/languages/prism/docker'
import makefile from 'react-syntax-highlighter/dist/esm/languages/prism/makefile'
import cmake from 'react-syntax-highlighter/dist/esm/languages/prism/cmake'
import nginx from 'react-syntax-highlighter/dist/esm/languages/prism/nginx'
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql'
import graphql from 'react-syntax-highlighter/dist/esm/languages/prism/graphql'
import protobuf from 'react-syntax-highlighter/dist/esm/languages/prism/protobuf'
import diff from 'react-syntax-highlighter/dist/esm/languages/prism/diff'
import git from 'react-syntax-highlighter/dist/esm/languages/prism/git'
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown'
import latex from 'react-syntax-highlighter/dist/esm/languages/prism/latex'
import c from 'react-syntax-highlighter/dist/esm/languages/prism/c'
import cpp from 'react-syntax-highlighter/dist/esm/languages/prism/cpp'
import csharp from 'react-syntax-highlighter/dist/esm/languages/prism/csharp'
import java from 'react-syntax-highlighter/dist/esm/languages/prism/java'
import kotlin from 'react-syntax-highlighter/dist/esm/languages/prism/kotlin'
import scala from 'react-syntax-highlighter/dist/esm/languages/prism/scala'
import go from 'react-syntax-highlighter/dist/esm/languages/prism/go'
import rust from 'react-syntax-highlighter/dist/esm/languages/prism/rust'
import swift from 'react-syntax-highlighter/dist/esm/languages/prism/swift'
import objectivec from 'react-syntax-highlighter/dist/esm/languages/prism/objectivec'
import dart from 'react-syntax-highlighter/dist/esm/languages/prism/dart'
import ruby from 'react-syntax-highlighter/dist/esm/languages/prism/ruby'
import php from 'react-syntax-highlighter/dist/esm/languages/prism/php'
import lua from 'react-syntax-highlighter/dist/esm/languages/prism/lua'
import perl from 'react-syntax-highlighter/dist/esm/languages/prism/perl'
import r from 'react-syntax-highlighter/dist/esm/languages/prism/r'
import julia from 'react-syntax-highlighter/dist/esm/languages/prism/julia'
import haskell from 'react-syntax-highlighter/dist/esm/languages/prism/haskell'
import elixir from 'react-syntax-highlighter/dist/esm/languages/prism/elixir'
import erlang from 'react-syntax-highlighter/dist/esm/languages/prism/erlang'
import clojure from 'react-syntax-highlighter/dist/esm/languages/prism/clojure'
import elm from 'react-syntax-highlighter/dist/esm/languages/prism/elm'
import ocaml from 'react-syntax-highlighter/dist/esm/languages/prism/ocaml'
import fsharp from 'react-syntax-highlighter/dist/esm/languages/prism/fsharp'
import vim from 'react-syntax-highlighter/dist/esm/languages/prism/vim'
import hcl from 'react-syntax-highlighter/dist/esm/languages/prism/hcl'
import { apiFetch } from './utils/api.js'
import './Modal.css'

const LANGS = {
  python, javascript, typescript, jsx, tsx, json, css, scss, sass, less,
  markup, yaml, toml, ini, bash, batch, powershell, docker, makefile, cmake,
  nginx, sql, graphql, protobuf, diff, git, markdown, latex,
  c, cpp, csharp, java, kotlin, scala, go, rust, swift, objectivec, dart,
  ruby, php, lua, perl, r, julia, haskell, elixir, erlang, clojure, elm,
  ocaml, fsharp, vim, hcl,
}
for (const [name, lang] of Object.entries(LANGS)) {
  SyntaxHighlighter.registerLanguage(name, lang)
}

const EXT_TO_LANG = {
  // Python
  py: 'python', pyi: 'python', pyw: 'python',
  // JS / TS
  js: 'javascript', cjs: 'javascript', mjs: 'javascript',
  ts: 'typescript', cts: 'typescript', mts: 'typescript',
  jsx: 'jsx', tsx: 'tsx',
  // Web
  json: 'json', json5: 'json', jsonc: 'json',
  css: 'css', scss: 'scss', sass: 'sass', less: 'less',
  html: 'markup', htm: 'markup', xml: 'markup', svg: 'markup', xhtml: 'markup',
  vue: 'markup', svelte: 'markup',
  // Config
  yaml: 'yaml', yml: 'yaml',
  toml: 'toml',
  ini: 'ini', cfg: 'ini', conf: 'ini', properties: 'ini', editorconfig: 'ini',
  env: 'bash',
  // Shell
  sh: 'bash', bash: 'bash', zsh: 'bash', fish: 'bash',
  bat: 'batch', cmd: 'batch',
  ps1: 'powershell', psm1: 'powershell', psd1: 'powershell',
  // Build / Infra
  dockerfile: 'docker',
  makefile: 'makefile', mk: 'makefile',
  cmake: 'cmake',
  tf: 'hcl', tfvars: 'hcl', hcl: 'hcl',
  // Data / Schema
  sql: 'sql',
  graphql: 'graphql', gql: 'graphql',
  proto: 'protobuf',
  // Diff / VCS
  diff: 'diff', patch: 'diff',
  gitignore: 'git', gitattributes: 'git', gitconfig: 'git',
  // Docs
  md: 'markdown', mdx: 'markdown', markdown: 'markdown',
  tex: 'latex', ltx: 'latex',
  // Systems
  c: 'c', h: 'c',
  cpp: 'cpp', cxx: 'cpp', cc: 'cpp', hpp: 'cpp', hxx: 'cpp', hh: 'cpp',
  cs: 'csharp', csx: 'csharp',
  java: 'java',
  kt: 'kotlin', kts: 'kotlin',
  scala: 'scala', sc: 'scala',
  go: 'go',
  rs: 'rust',
  swift: 'swift',
  m: 'objectivec', mm: 'objectivec',
  dart: 'dart',
  // Scripting
  rb: 'ruby', rake: 'ruby', gemspec: 'ruby',
  php: 'php', phtml: 'php',
  lua: 'lua',
  pl: 'perl', pm: 'perl',
  r: 'r', rmd: 'r',
  jl: 'julia',
  // Functional
  hs: 'haskell', lhs: 'haskell',
  ex: 'elixir', exs: 'elixir',
  erl: 'erlang', hrl: 'erlang',
  clj: 'clojure', cljs: 'clojure', cljc: 'clojure', edn: 'clojure',
  elm: 'elm',
  ml: 'ocaml', mli: 'ocaml',
  fs: 'fsharp', fsx: 'fsharp', fsi: 'fsharp',
  // Misc
  vim: 'vim', vimrc: 'vim',
  // Nginx
  nginx: 'nginx',
}

// 拡張子なしファイル (basename で判定)
const BASENAME_TO_LANG = {
  dockerfile: 'docker',
  containerfile: 'docker',
  makefile: 'makefile',
  gnumakefile: 'makefile',
  cmakelists: 'cmake',
  rakefile: 'ruby',
  gemfile: 'ruby',
  procfile: 'bash',
  '.zshrc': 'bash', '.bashrc': 'bash', '.profile': 'bash', '.bash_profile': 'bash',
  '.vimrc': 'vim',
  '.gitignore': 'git', '.gitattributes': 'git', '.gitconfig': 'git',
  '.env': 'bash',
  '.editorconfig': 'ini',
}

function detectLang(path) {
  const base = path.split('/').pop() || ''
  const lower = base.toLowerCase()
  if (BASENAME_TO_LANG[lower]) return BASENAME_TO_LANG[lower]
  const ext = (base.includes('.') ? base.split('.').pop() : '').toLowerCase()
  return EXT_TO_LANG[ext] || null
}

const TEXT_EXTENSIONS = new Set([
  ...Object.keys(EXT_TO_LANG),
  'txt', 'log', 'csv', 'tsv', 'lock', 'list', 'text',
])

export default function FilePreviewModal({ path, onClose }) {
  const [content, setContent] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [editMode, setEditMode] = useState(false)
  const [editText, setEditText] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)

  const base = (path.split('/').pop() || '').toLowerCase()
  const ext = (base.includes('.') ? base.split('.').pop() : '').toLowerCase()
  const isMarkdown = /\.(md|mdx|markdown)$/i.test(path)
  const lang = detectLang(path)
  const isEditable = TEXT_EXTENSIONS.has(ext) || BASENAME_TO_LANG[base] !== undefined || lang !== null

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    setContent(null)
    apiFetch(`/file?path=${encodeURIComponent(path)}`, { signal: controller.signal })
      .then(r => {
        if (r.status === 413) return r.json().then(d => Promise.reject(d.detail || 'ファイルが大きすぎます'))
        return r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`)
      })
      .then(data => setContent(data.content))
      .catch(e => { if (e.name !== 'AbortError') setError(typeof e === 'string' ? e : `読み込みエラー`) })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [path])

  const handleEdit = useCallback(() => {
    setEditText(content ?? '')
    setSaveError(null)
    setEditMode(true)
  }, [content])

  const handleCancel = useCallback(() => {
    setEditMode(false)
    setSaveError(null)
  }, [])

  const handleSave = useCallback(async () => {
    if (!window.confirm(`このファイルを上書き保存しますか?\n${path}`)) return
    setSaving(true)
    setSaveError(null)
    try {
      const res = await apiFetch(`/file`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, content: editText }),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        throw new Error(d.detail || `HTTP ${res.status}`)
      }
      setContent(editText)
      setEditMode(false)
    } catch (e) {
      setSaveError(e.message)
    } finally {
      setSaving(false)
    }
  }, [path, editText])

  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        if (editMode) handleCancel()
        else onClose()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose, editMode, handleCancel])

  return (
    <div className="modal-overlay modal-overlay-preview" onClick={editMode ? undefined : onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-path">{path}</span>
          <div className="modal-actions">
            {!editMode && isEditable && content !== null && (
              <button className="modal-edit-btn" onClick={handleEdit}>編集</button>
            )}
            {editMode && (
              <>
                <button className="modal-save-btn" onClick={handleSave} disabled={saving}>
                  {saving ? '保存中...' : '保存'}
                </button>
                <button className="modal-cancel-btn" onClick={handleCancel} disabled={saving}>キャンセル</button>
              </>
            )}
            {!editMode && <button className="modal-close" onClick={onClose}>✕</button>}
          </div>
        </div>
        <div className="modal-body">
          {loading && <span className="dim">読み込み中...</span>}
          {error && <span className="error">{error}</span>}
          {saveError && <span className="error">保存エラー: {saveError}</span>}
          {editMode ? (
            <textarea
              className="file-editor"
              value={editText}
              onChange={e => setEditText(e.target.value)}
              spellCheck={false}
              autoFocus
            />
          ) : content !== null && (
            isMarkdown ? (
              <div className="md-preview">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {content}
                </ReactMarkdown>
              </div>
            ) : lang ? (
              <SyntaxHighlighter
                language={lang}
                style={oneDark}
                customStyle={{ margin: 0, borderRadius: 0, fontSize: '12px', background: 'transparent' }}
                showLineNumbers
              >
                {content}
              </SyntaxHighlighter>
            ) : (
              <pre className="file-content">{content}</pre>
            )
          )}
        </div>
      </div>
    </div>
  )
}
