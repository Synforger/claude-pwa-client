import React, { useRef, useState, useCallback, useDeferredValue, useMemo, Profiler } from 'react'
import { useT } from '../../i18n/t.js'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { visit } from 'unist-util-visit'
import { useThrottledStreamingText } from './useThrottledStreamingText.js'
import { recordPerfSample } from '../../features/app-effects/perfProbe.js'
import './MessageRenderer.css'

const PATH_RE = /(?<![(`])(~\/[^\s`"')\]]+|\/Users\/[^\s`"')\]]+)/g

// 長いメッセージの扱いは 2 段。 役割ごとに閾値を分ける (= 1 つの数字で兼ねると、 守りたい
// degeneration と畳みたい長文が 2 桁離れているので両立しない)。
//   ① 折りたたみ (= 読みやすさ): COLLAPSE_CHARS 超は markdown を保ったまま先頭だけ描画し、
//      残りは展開ボタンで開く。 畳んでいる間も展開後も読み味は普通の返答と同じ。
//   ② plain 退避 (= 重さ対策): PLAIN_FALLBACK_CHARS 超は markdown を通さない。 出力
//      degeneration (= 同一語の数万回反復等) が数万個の DOM ノードに展開してメインスレッドを
//      固める事故を防ぐ (= スクロール / ステータスライン更新も巻き添えで停止、 2026-06 実害)。
// 値の根拠 (= 2026-09-08 実測、 jsonl 470 本 / assistant 本文 22,003 件): 中央値 90 字 /
// p99 3,613 字 / 正常系の最大 25,916 字 (= subagent transcript) に対し degeneration は
// 518,658 字。 4,000 超は 0.78% なので日常の長文は畳まれず、 30,000 超は degeneration だけ。
export const COLLAPSE_CHARS = 4_000
export const PLAIN_FALLBACK_CHARS = 30_000
// 折りたたみ時のプレビュー長 (= ブロック境界まで下げて切るので実際はこれ以下になる)。
const COLLAPSE_PREVIEW_CHARS = 2_000
// plain 退避時のプレビュー長 (= markdown を通さない経路なので、 畳まれていると分かる程度)。
const LARGE_PREVIEW_CHARS = 800

// markdown を通さず plain text に倒すべき巨大メッセージか。 純関数 (= テスト対象)。
export function isOversizedMessage(text) {
  return typeof text === 'string' && text.length > PLAIN_FALLBACK_CHARS
}

// markdown を保ったまま畳むべき長文か。 純関数 (= テスト対象)。
export function isCollapsibleMessage(text) {
  return typeof text === 'string' && text.length > COLLAPSE_CHARS
}

/** markdown を壊さない位置で先頭 max 字までを切り出す純関数。
 *
 * 切り位置はコードフェンスの外側のブロック境界 (= 空行) だけ。 max を超える手前で最後に見た
 * 境界まで下げるので、 表もコードブロックも途中で切れない。 境界が 1 つも取れなければ行の
 * 切れ目まで戻し、 フェンスが開いたままなら閉じて返す (= 以降が全部コード扱いになるのを防ぐ)。
 * 1 行目だけで max を超える場合のみ文字数で切る (= 改行を持たない degeneration 系)。 */
export function previewUpTo(text, max) {
  if (typeof text !== 'string' || text.length <= max) return text
  const lines = text.split('\n')
  let inFence = false
  let len = 0
  let cut = -1   // 最後に見たフェンス外の空行 (= ここまでを返す)
  let last = -1  // max に収まった最後の行
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const next = len + line.length + 1
    if (next > max) break
    if (/^\s*(```|~~~)/.test(line)) inFence = !inFence
    if (!inFence && line.trim() === '') cut = i
    len = next
    last = i
  }
  if (cut > 0) return lines.slice(0, cut).join('\n')
  if (last < 0) return text.slice(0, max)
  const head = lines.slice(0, last + 1).join('\n')
  return inFence ? `${head}\n\`\`\`` : head
}

// --- streaming 増分描画 (= 2026-07-15 電力最適化 R1) ---
//
// 旧: streaming 中、 伸び続ける全文を 500ms ごとに ReactMarkdown で丸ごと再パース。
// 応答長 n に対し 1 tick O(n)、 累積 O(n^2) で長い応答ほど発熱していた (= 携帯が熱い主因)。
//
// 新: 確定済みブロック (= 空行区切り、 コードフェンス外) を CHUNK 単位に固定し、 各 CHUNK は
// React.memo で 1 回だけパース。 再パースが走るのは「伸びている末尾ブロック」 だけになり、
// 1 tick のコストが末尾サイズでほぼ一定になる。
//
// 見た目の等価性: 分割は top-level ブロック境界のみ (= フェンス内では絶対に切らない)。
// 万一 loose list 等で streaming 中の見た目が僅かに変わっても、 完了時 (= streaming=false)
// は従来どおり全文 1 回パースの単一 tree に置き換わるので、 最終表示は完全に従来と同一。
const STREAM_CHUNK_MIN_CHARS = 1_500

/** streaming テキストを (確定 chunk 列, 伸び続ける末尾) に分割する純関数。
 *
 * 境界 = コードフェンス外の空行。 直近の境界より後ろは「まだ伸びる」 とみなして tail。
 * chunk は STREAM_CHUNK_MIN_CHARS を超えたら閉じる (= chunk 数を抑えて memo 比較を安く)。
 * text は append-only なので、 過去に閉じた chunk の substring は不変 = memo が効く。 */
export function splitStreamingBlocks(text) {
  const lines = text.split('\n')
  const chunks = []
  let cur = []          // 今組み立て中の chunk の行
  let curLen = 0
  let block = []        // 今のブロック (= 最後の空行以降) の行
  let inFence = false
  for (const line of lines) {
    if (/^\s*(```|~~~)/.test(line)) inFence = !inFence
    if (!inFence && line.trim() === '') {
      // ブロック境界: block を chunk へ確定
      cur.push(...block, line)
      curLen += block.reduce((a, l) => a + l.length + 1, 0) + line.length + 1
      block = []
      if (curLen >= STREAM_CHUNK_MIN_CHARS) {
        chunks.push(cur.join('\n'))
        cur = []
        curLen = 0
      }
    } else {
      block.push(line)
    }
  }
  // cur に残った確定ブロックも chunk として閉じる (= tail は最後の未完ブロックのみ)。
  // 空白のみの chunk は描画に寄与しないので捨てる (= 空文字入力で chunks=[''] を作らない)
  if (cur.length > 0 && cur.some(l => l.trim() !== '')) chunks.push(cur.join('\n'))
  return { chunks, tail: block.join('\n') }
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
  const t = useT()
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
        aria-label={t('code.copy')}
      >
        {state === 'copied' ? '✓' : state === 'failed' ? '✗' : 'copy'}
      </button>
    </div>
  )
}

// url sanitizer は全 render 共通の純関数 (= identity 安定、 memo を壊さない)。
function urlTransform(url) {
  // cpc-file:// は内部で onOpenFile に流す独自スキーム = pass-through。
  // それ以外は react-markdown 既定の sanitizer を使い、 javascript: / data:
  // 等の危険スキームをブロック。 過去ここで `(url) => url` にしてた結果、
  // 任意 URL スキームがそのまま <a href> に出ていた (XSS 経路)。
  if (typeof url === 'string' && url.startsWith('cpc-file://')) return url
  return defaultUrlTransform(url)
}

// components map の factory。 onOpenFile ごとに 1 回だけ作る (= chunk memo が効く前提。
// inline で毎 render 新 object を作ると全 chunk が memo 貫通して再パースされる)。
function buildComponents(onOpenFile) {
  return {
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
  }
}

// 確定 chunk の描画単体。 memo + text/props 不変で再 render されない = パースは chunk
// 生成時の 1 回だけ (= streaming 増分描画の心臓部)。
const MarkdownChunk = React.memo(function MarkdownChunk({ text, plugins, components }) {
  return (
    <ReactMarkdown remarkPlugins={plugins} urlTransform={urlTransform} components={components}>
      {text}
    </ReactMarkdown>
  )
})

// 長文を markdown のまま畳む。 プレビューはブロック境界で切るので、 畳んでいる間も表や
// コードブロックが途中で壊れない。 展開は同じ markdown 経路へ全文を通すだけなので、
// 折りたたみの前後で読み味が変わらない (= 旧実装は展開すると生の markdown が出ていた)。
function CollapsibleMarkdown({ text, plugins, components }) {
  const t = useT()
  const [expanded, setExpanded] = useState(false)
  const preview = useMemo(() => previewUpTo(text, COLLAPSE_PREVIEW_CHARS), [text])
  return (
    <div className="md-collapsible">
      <MarkdownChunk
        text={expanded ? text : preview}
        plugins={plugins}
        components={components}
      />
      <button
        type="button"
        className="md-collapse-toggle"
        onClick={() => setExpanded((v) => !v)}
      >
        {expanded
          ? t('message.collapsed.collapse')
          : t('message.collapsed.show_full', { n: text.length.toLocaleString() })}
      </button>
    </div>
  )
}

const MessageRenderer = React.memo(function MessageRenderer({ text, onOpenFile, streaming }) {
  // 2026-07-10 発熱対策: streaming 中の markdown 更新を 500ms に 1 回へ間引く。 完了時は即最終形。
  // 2026-07-15 R1: さらに増分化 — 再パースは「伸びている末尾ブロック」 だけ (= 下の chunk 分割)。
  const throttledText = useThrottledStreamingText(text, streaming)

  // 発熱調査 段階 2 (= 2026-07-13): この message subtree の render 実測を beacon に流す。
  // React 公式の Profiler (= actualDuration) を使う。 memo 済みなので再 render された
  // message しか記録されない。 markdown パース (= remark) は render 中に走るので
  // actualDuration に含まれる。 DOM layout / paint は含まれない (= それは stall 側で見る)。
  const onProfile = useCallback(
    (_id, _phase, actualDuration) => {
      recordPerfSample('md-render', actualDuration, {
        len: text.length,
        streaming: !!streaming,
      })
    },
    [text.length, streaming],
  )
  // F-24: さらに useDeferredValue で優先度も下げ、 入力 (= scroll / tap) を優先描画する。
  const deferredText = useDeferredValue(throttledText)

  // F-23: streaming 中はファイルパスのリンク化を skip する (= 不完全パスを毎フレーム
  // 探索して visit する処理は streaming 1 文字ごとに発火するので重い)。 完了後の最終
  // text で 1 回だけ走らせれば見た目は同じ。 remarkPlugins 配列は memo 化して
  // ReactMarkdown 内部の effect を毎回再評価させない。
  const plugins = useMemo(
    () => (streaming ? [remarkGfm] : [remarkGfm, remarkFilePaths]),
    [streaming],
  )
  const components = useMemo(() => buildComponents(onOpenFile), [onOpenFile])

  // streaming 中のみ chunk 分割 (= 完了時は従来どおり全文 1 tree、 最終表示は完全互換)。
  const streamingParts = useMemo(
    () => (streaming ? splitStreamingBlocks(deferredText) : null),
    [streaming, deferredText],
  )

  // 巨大メッセージは markdown を通さず plain text に倒す (= degeneration 等でメインスレッドが
  // 固まるのを防ぐ)。 streaming 中で途中まで巨大になったものも同様にガードされる。
  // deferred ではなく現在 text で判定 (= 巨大化を遅らせず即時に重い経路を切る)。
  if (isOversizedMessage(text)) {
    return <LargeTextMessage text={text} />
  }
  if (streamingParts) {
    // streaming 中: 確定 chunk は memo で再パースゼロ、 末尾だけ 500ms ごとに再パース。
    // 不完全な Markdown (閉じてない表/フェンス) でも react-markdown は例外を吐かない。
    return (
      <Profiler id="md-render" onRender={onProfile}>
        {streamingParts.chunks.map((c, i) => (
          <MarkdownChunk key={i} text={c} plugins={plugins} components={components} />
        ))}
        <MarkdownChunk text={streamingParts.tail} plugins={plugins} components={components} />
      </Profiler>
    )
  }
  // 長文は markdown のまま畳む (= 描画する text で判定して、 表示と判定をずらさない)。
  if (isCollapsibleMessage(deferredText)) {
    return (
      <Profiler id="md-render" onRender={onProfile}>
        <CollapsibleMarkdown text={deferredText} plugins={plugins} components={components} />
      </Profiler>
    )
  }
  return (
    <Profiler id="md-render" onRender={onProfile}>
      <MarkdownChunk text={deferredText} plugins={plugins} components={components} />
    </Profiler>
  )
})

export default MessageRenderer
