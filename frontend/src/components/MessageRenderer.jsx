import React, { useRef, useState, useCallback, useDeferredValue, useMemo } from 'react'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { visit } from 'unist-util-visit'
import './MessageRenderer.css'

const PATH_RE = /(?<![(`])(~\/[^\s`"')\]]+|\/Users\/[^\s`"')\]]+)/g

// 単一メッセージの折りたたみ境界 (文字数)。 これを超えたら markdown を通さず plain text で
// 折りたたむ (先頭プレビュー + 展開ボタン)。 2 つの役割を兼ねる:
//   ① 重さ対策: 出力 degeneration (= 同一語の数万回反復等) で巨大メッセージが来ても、
//      markdown が数万個の DOM ノードに展開してメインスレッドを固める事故を防ぐ
//      (スクロール / ステータスライン更新も巻き添えで停止していた、 2026-06 実害)。
//   ② 可視化 UX: 長い出力はデフォルトで畳んで一覧性を保つ。
// 値の性格: Discord/WhatsApp 等の「これ以上打てないハード上限 (2k〜64k)」とは別軸で、
// あくまで「読みやすさのために畳む境界」。 折りたたみ (全文は展開で見れる) なので短くてよい。
// 運用判断 (2026-06): まず 10000 で運用、 鬱陶しければ調整する。
export const MARKDOWN_MAX_CHARS = 10_000
// 折りたたみ時の先頭プレビュー長 (= ここまで出して残りは展開ボタン)。 閾値より十分小さくして
// 「畳まれている」 ことが分かる長さにする。
const LARGE_PREVIEW_CHARS = 800

// markdown を通さず plain text に倒すべき巨大メッセージか。 純関数 (= テスト対象)。
export function isOversizedMessage(text) {
  return typeof text === 'string' && text.length > MARKDOWN_MAX_CHARS
}

// 巨大テキストを markdown を介さず plain text で描画する。 既定は先頭だけ、 ボタンで全文。
// 全文展開しても 1 個の <pre> テキストノードなので DOM ノード爆発は起きない。
function LargeTextMessage({ text }) {
  const [expanded, setExpanded] = useState(false)
  const kb = Math.max(1, Math.round(text.length / 1024))
  const truncated = !expanded && text.length > LARGE_PREVIEW_CHARS
  const shown = truncated ? text.slice(0, LARGE_PREVIEW_CHARS) + '…' : text
  return (
    <div className="md-oversized">
      <div className="md-oversized-note">
        ⚠ Large message ({kb.toLocaleString()} KB) — shown as plain text to keep the app responsive.
      </div>
      <pre className="md-plain">{shown}</pre>
      {text.length > LARGE_PREVIEW_CHARS && (
        <button
          type="button"
          className="md-oversized-toggle"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? 'Collapse' : `Show full (${kb.toLocaleString()} KB)`}
        </button>
      )}
    </div>
  )
}

// remarkプラグイン: テキストノード内のファイルパスをlinkノードに変換
function remarkFilePaths() {
  return (tree) => {
    visit(tree, 'text', (node, index, parent) => {
      if (!parent || index == null) return
      PATH_RE.lastIndex = 0
      if (!PATH_RE.test(node.value)) return

      PATH_RE.lastIndex = 0
      const parts = []
      let last = 0
      let match

      while ((match = PATH_RE.exec(node.value)) !== null) {
        if (match.index > last) {
          parts.push({ type: 'text', value: node.value.slice(last, match.index) })
        }
        parts.push({
          type: 'link',
          url: `cpc-file://${encodeURIComponent(match[0])}`,
          children: [{ type: 'text', value: match[0] }],
        })
        last = match.index + match[0].length
      }
      if (last < node.value.length) {
        parts.push({ type: 'text', value: node.value.slice(last) })
      }

      parent.children.splice(index, 1, ...parts)
    })

    // インラインコード（`~/...`）もリンクに変換
    visit(tree, 'inlineCode', (node, index, parent) => {
      if (!parent || index == null) return
      if (!/^(~\/|\/Users\/)/.test(node.value)) return
      parent.children.splice(index, 1, {
        type: 'link',
        url: `cpc-file://${encodeURIComponent(node.value)}`,
        children: [{ type: 'text', value: node.value }],
      })
    })
  }
}

// コードブロック描画 + 右上「コピー」 ボタン。 textContent を navigator.clipboard.writeText で
// 投げる素朴実装。 PWA は Tailscale HTTPS 経由なので iOS Safari でも writeText が動く。
// 失敗時 (= clipboard permission denied / 非 secure context) は console.error のみ、 表示は
// 「✗」 で 1.5 秒。
function CodeBlock({ children }) {
  const ref = useRef(null)
  const [state, setState] = useState('idle') // 'idle' | 'copied' | 'failed'
  const timerRef = useRef(null)
  const onCopy = useCallback(async (e) => {
    e.stopPropagation()
    const text = ref.current?.textContent ?? ''
    try {
      await navigator.clipboard.writeText(text)
      setState('copied')
    } catch (err) {
      console.error('copy failed', err)
      setState('failed')
    }
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => setState('idle'), 1500)
  }, [])
  return (
    <div className="md-code-wrap">
      <pre ref={ref} className="md-code">{children}</pre>
      <button
        type="button"
        className="md-code-copy"
        onClick={onCopy}
        aria-label="コードをコピー"
      >
        {state === 'copied' ? '✓' : state === 'failed' ? '✗' : 'copy'}
      </button>
    </div>
  )
}

const MessageRenderer = React.memo(function MessageRenderer({ text, onOpenFile, streaming }) {
  // F-24: streaming 中は text が毎 rAF 更新されて重い markdown 再 parse が連続する。
  // useDeferredValue で markdown レンダリングを 1 段遅延させ、 入力 (= scroll / tap) を
  // 優先描画する。 streaming 完了後は最終 text で同期に追い付く。
  const deferredText = useDeferredValue(text)

  // F-23: streaming 中はファイルパスのリンク化を skip する (= 不完全パスを毎フレーム
  // 探索して visit する処理は streaming 1 文字ごとに発火するので重い)。 完了後の最終
  // text で 1 回だけ走らせれば見た目は同じ。 remarkPlugins 配列は memo 化して
  // ReactMarkdown 内部の effect を毎回再評価させない。
  const plugins = useMemo(
    () => (streaming ? [remarkGfm] : [remarkGfm, remarkFilePaths]),
    [streaming],
  )

  // 巨大メッセージは markdown を通さず plain text に倒す (= degeneration 等でメインスレッドが
  // 固まるのを防ぐ)。 streaming 中で途中まで巨大になったものも同様にガードされる。
  // deferred ではなく現在 text で判定 (= 巨大化を遅らせず即時に重い経路を切る)。
  if (isOversizedMessage(text)) {
    return <LargeTextMessage text={text} />
  }
  // streaming 中も ReactMarkdown を通す。不完全な Markdown (閉じてない表/コードブロック等) でも
  // react-markdown は例外を吐かず、暫定の見た目で描画する。途中の表やコードが視覚的に見えないよりマシ。
  return (
    <ReactMarkdown
      remarkPlugins={plugins}
      urlTransform={(url) => {
        // cpc-file:// は内部で onOpenFile に流す独自スキーム = pass-through。
        // それ以外は react-markdown 既定の sanitizer を使い、 javascript: / data:
        // 等の危険スキームをブロック。 過去ここで `(url) => url` にしてた結果、
        // 任意 URL スキームがそのまま <a href> に出ていた (XSS 経路)。
        if (typeof url === 'string' && url.startsWith('cpc-file://')) return url
        return defaultUrlTransform(url)
      }}
      components={{
        a({ href, children }) {
          if (href?.startsWith('cpc-file://')) {
            let path
            try { path = decodeURIComponent(href.slice('cpc-file://'.length)) } catch { path = href.slice('cpc-file://'.length) }
            return (
              <span className="file-link" onClick={() => onOpenFile(path)}>
                {children}
              </span>
            )
          }
          return <a href={href} target="_blank" rel="noreferrer">{children}</a>
        },
        pre({ children }) {
          return <CodeBlock>{children}</CodeBlock>
        },
        code({ className, children }) {
          if (!className) return <code className="inline-code">{children}</code>
          return <code className={className}>{children}</code>
        },
        table({ children }) {
          return <div className="table-wrapper"><table>{children}</table></div>
        },
      }}
    >
      {deferredText}
    </ReactMarkdown>
  )
})

export default MessageRenderer
