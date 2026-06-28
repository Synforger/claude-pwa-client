import { useState, useEffect, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
// 頻出 10 言語は eager (= 開いた瞬間にハイライト可能、 初期 bundle に乗る)。
// 残り ~40 言語は detectLang で必要になった時だけ動的 import (= F-49、 50 言語全部 eager
// から「使うものだけ取り寄せる」 戦略に切替。 初期 chunk から ~80% の prism 言語を外す)。
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python'
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript'
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript'
import jsx from 'react-syntax-highlighter/dist/esm/languages/prism/jsx'
import tsx from 'react-syntax-highlighter/dist/esm/languages/prism/tsx'
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json'
import css from 'react-syntax-highlighter/dist/esm/languages/prism/css'
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash'
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml'
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown'
import { apiFetch } from '../../utils/api.js'
import { isFav, toggleFav, subscribeFavs } from '../file-tree/favorites.js'
import { useEscape } from '../../hooks/useEscape.js'
import ConfirmDialog from '../../shared/ConfirmDialog.jsx'
import '../../styles/Modal.css'

// eager 言語 (= 頻出 10 個)。 初期 bundle に乗る。
const EAGER_LANGS = {
  python, javascript, typescript, jsx, tsx, json, css, bash, yaml, markdown,
}
// すでに registerLanguage 済の言語名 set (= 再 register を避ける + 動的 load 済 track)。
const registeredLangs = new Set()
for (const [name, lang] of Object.entries(EAGER_LANGS)) {
  SyntaxHighlighter.registerLanguage(name, lang)
  registeredLangs.add(name)
}

// lazy 言語 → dynamic import 関数。 Vite は dynamic import の引数を解析して個別 chunk に
// 分けてくれる。 detectLang が返す名前 = この map の key。
// 未掲載の言語名は「ハイライトなし pre 表示」 にフォールバック (= 過剰最適化を防ぐ)。
const LAZY_LANG_LOADERS = {
  scss: () => import('react-syntax-highlighter/dist/esm/languages/prism/scss'),
  sass: () => import('react-syntax-highlighter/dist/esm/languages/prism/sass'),
  less: () => import('react-syntax-highlighter/dist/esm/languages/prism/less'),
  markup: () => import('react-syntax-highlighter/dist/esm/languages/prism/markup'),
  toml: () => import('react-syntax-highlighter/dist/esm/languages/prism/toml'),
  ini: () => import('react-syntax-highlighter/dist/esm/languages/prism/ini'),
  batch: () => import('react-syntax-highlighter/dist/esm/languages/prism/batch'),
  powershell: () => import('react-syntax-highlighter/dist/esm/languages/prism/powershell'),
  docker: () => import('react-syntax-highlighter/dist/esm/languages/prism/docker'),
  makefile: () => import('react-syntax-highlighter/dist/esm/languages/prism/makefile'),
  cmake: () => import('react-syntax-highlighter/dist/esm/languages/prism/cmake'),
  nginx: () => import('react-syntax-highlighter/dist/esm/languages/prism/nginx'),
  sql: () => import('react-syntax-highlighter/dist/esm/languages/prism/sql'),
  graphql: () => import('react-syntax-highlighter/dist/esm/languages/prism/graphql'),
  protobuf: () => import('react-syntax-highlighter/dist/esm/languages/prism/protobuf'),
  diff: () => import('react-syntax-highlighter/dist/esm/languages/prism/diff'),
  git: () => import('react-syntax-highlighter/dist/esm/languages/prism/git'),
  latex: () => import('react-syntax-highlighter/dist/esm/languages/prism/latex'),
  c: () => import('react-syntax-highlighter/dist/esm/languages/prism/c'),
  cpp: () => import('react-syntax-highlighter/dist/esm/languages/prism/cpp'),
  csharp: () => import('react-syntax-highlighter/dist/esm/languages/prism/csharp'),
  java: () => import('react-syntax-highlighter/dist/esm/languages/prism/java'),
  kotlin: () => import('react-syntax-highlighter/dist/esm/languages/prism/kotlin'),
  scala: () => import('react-syntax-highlighter/dist/esm/languages/prism/scala'),
  go: () => import('react-syntax-highlighter/dist/esm/languages/prism/go'),
  rust: () => import('react-syntax-highlighter/dist/esm/languages/prism/rust'),
  swift: () => import('react-syntax-highlighter/dist/esm/languages/prism/swift'),
  objectivec: () => import('react-syntax-highlighter/dist/esm/languages/prism/objectivec'),
  dart: () => import('react-syntax-highlighter/dist/esm/languages/prism/dart'),
  ruby: () => import('react-syntax-highlighter/dist/esm/languages/prism/ruby'),
  php: () => import('react-syntax-highlighter/dist/esm/languages/prism/php'),
  lua: () => import('react-syntax-highlighter/dist/esm/languages/prism/lua'),
  perl: () => import('react-syntax-highlighter/dist/esm/languages/prism/perl'),
  r: () => import('react-syntax-highlighter/dist/esm/languages/prism/r'),
  julia: () => import('react-syntax-highlighter/dist/esm/languages/prism/julia'),
  haskell: () => import('react-syntax-highlighter/dist/esm/languages/prism/haskell'),
  elixir: () => import('react-syntax-highlighter/dist/esm/languages/prism/elixir'),
  erlang: () => import('react-syntax-highlighter/dist/esm/languages/prism/erlang'),
  clojure: () => import('react-syntax-highlighter/dist/esm/languages/prism/clojure'),
  elm: () => import('react-syntax-highlighter/dist/esm/languages/prism/elm'),
  ocaml: () => import('react-syntax-highlighter/dist/esm/languages/prism/ocaml'),
  fsharp: () => import('react-syntax-highlighter/dist/esm/languages/prism/fsharp'),
  vim: () => import('react-syntax-highlighter/dist/esm/languages/prism/vim'),
  hcl: () => import('react-syntax-highlighter/dist/esm/languages/prism/hcl'),
}

// lazy load + register。 既に登録済 / loader 未登録なら no-op。
async function ensureLangRegistered(name) {
  if (!name || registeredLangs.has(name)) return true
  const loader = LAZY_LANG_LOADERS[name]
  if (!loader) return false
  try {
    const mod = await loader()
    SyntaxHighlighter.registerLanguage(name, mod.default)
    registeredLangs.add(name)
    return true
  } catch {
    return false
  }
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

  // F-50: window.confirm を ConfirmDialog 化。 modal 内 modal なので Escape はキャンセル扱い。
  const [saveConfirm, setSaveConfirm] = useState(false)
  // F-49: lang ハイライタが register 済になったかの flag。 lazy 言語は async load 後に true。
  const [langReady, setLangReady] = useState(() => false)

  const [favored, setFavored] = useState(() => isFav(path))
  useEffect(() => {
    setFavored(isFav(path))
    return subscribeFavs(() => setFavored(isFav(path)))
  }, [path])
  const handleToggleFav = useCallback(() => {
    toggleFav(path, false, path.split('/').pop() || path)
    setFavored(isFav(path))
  }, [path])

  // lang が変わった時 (= path 切替) に必要なハイライタを動的 load。 register 済 / eager は即 true。
  useEffect(() => {
    let cancelled = false
    if (!lang) { setLangReady(true); return undefined }
    if (registeredLangs.has(lang)) { setLangReady(true); return undefined }
    setLangReady(false)
    ensureLangRegistered(lang).then(() => {
      if (!cancelled) setLangReady(true)
    })
    return () => { cancelled = true }
  }, [lang])

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

  // 保存実行 (= ConfirmDialog で「はい」 が押された後の本体)。
  const performSave = useCallback(async () => {
    setSaveConfirm(false)
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

  const handleSave = useCallback(() => setSaveConfirm(true), [])

  // Escape の挙動 (= F-29 集約): saveConfirm > editMode > 通常 で 1 段ずつ畳む。
  useEscape(() => {
    if (saveConfirm) setSaveConfirm(false)
    else if (editMode) handleCancel()
    else onClose()
  })

  return (
    <div className="modal-overlay modal-overlay-preview" onClick={editMode ? undefined : onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-path">{path}</span>
          <div className="modal-actions">
            {!editMode && (
              <button
                className={`modal-fav-btn ${favored ? 'on' : ''}`}
                onClick={handleToggleFav}
                title={favored ? 'お気に入りから削除' : 'お気に入りに登録'}
                aria-label="favorite"
              >{favored ? '★' : '☆'}</button>
            )}
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
            ) : lang && langReady ? (
              <SyntaxHighlighter
                language={lang}
                style={oneDark}
                customStyle={{ margin: 0, borderRadius: 0, fontSize: '12px', background: 'transparent' }}
                showLineNumbers
              >
                {content}
              </SyntaxHighlighter>
            ) : (
              // lang 不明 or lazy load 待ち中はハイライト無しで先に出す (= load 完了で再 render)。
              <pre className="file-content">{content}</pre>
            )
          )}
        </div>
        <ConfirmDialog
          open={saveConfirm}
          text={`このファイルを上書き保存しますか?\n${path}`}
          onCancel={() => setSaveConfirm(false)}
          onConfirm={performSave}
        />
      </div>
    </div>
  )
}
