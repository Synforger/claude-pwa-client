import React, { useRef, useState, useCallback, useDeferredValue, useMemo, Profiler } from 'react'
import { useT } from '../../i18n/t.js'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { visit } from 'unist-util-visit'
import { useThrottledStreamingText } from './useThrottledStreamingText.js'
import { recordPerfSample } from '../../features/app-effects/perfProbe.js'
import { apiUrl } from '../../utils/api.js'
import './MessageRenderer.css'

const PATH_RE = /(?<![(`])(~\/[^\s`"')\]]+|\/Users\/[^\s`"')\]]+)/g

// 長いメッセージの扱いは 2 段。 役割ごとに閾値を分ける (= 1 つの数字で兼ねると、 守りたい
// degeneration と畳みたい長文が 2 桁離れているので両立しない)。
//   ① 折りたたみ (= 読みやすさ): COLLAPSE_CHARS 超は markdown を保ったまま先頭だけ描画し、
//      残りは展開ボタンで開く。 畳んでいる間も展開後も読み味は普通の返答と同じ。
//   ② plain 退避 (= 重さ対策): code block の外が PLAIN_FALLBACK_CHARS を超えるか、 全体が
//      PLAIN_FALLBACK_TOTAL_CHARS を超えたら markdown を通さない。 出力 degeneration (= 同一語の
//      数万回反復等) が数万個の DOM ノードに展開してメインスレッドを固める事故を防ぐ (= スクロール /
//      ステータスライン更新も巻き添えで停止、 2026-06 実害)。
// 値の根拠 (= 2026-09-08 実測、 jsonl 470 本 / assistant 本文 22,003 件): 中央値 90 字 / p99 3,613 字 /
// 正常系の最大 25,916 字に対し degeneration は 518,658 字。 4,000 超は 0.78% なので日常の長文は畳まれない。
// 重さは字数ではなく展開される要素の数で決まる (= 2026-10-19 実測、 jsdom で全部を描く時間): code block
// 1 つは 4 要素で 40,000 字 8 ms / 200,000 字 32 ms、 箇条書きは 40,000 字 93 ms、 表は 40,000 字 338 ms・
// 200,000 字 5.5 s、 同じ行の反復は 40,000 字 485 ms・200,000 字 5.9 s。 なので code block の中は数えず、
// 外だけを 30,000 字 (= 表と反復で 200〜300 ms の所) で切る。 全体の上限は code block だけの文も含めた
// 最後の守り。
export const COLLAPSE_CHARS = 4_000
export const PLAIN_FALLBACK_CHARS = 30_000
export const PLAIN_FALLBACK_TOTAL_CHARS = 200_000
// 折りたたみ時のプレビュー長 (= ブロック境界まで下げて切るので実際はこれ以下になる)。
const COLLAPSE_PREVIEW_CHARS = 2_000
// plain 退避時のプレビュー長 (= markdown を通さない経路なので、 畳まれていると分かる程度)。
const LARGE_PREVIEW_CHARS = 800

// code block (= ``` か ~~~ の囲み) の外の字数。 CommonMark の囲みに合わせる: 開きは行頭の空白 3 個まで、
// 閉じは同じ記号で開きと同じ長さ以上、 閉じが無ければ最後まで中。 囲みと言い切れない行 (= 字下げ 4 以上、
// list の中の囲み) は外に数える (= 多めに数えて、 重い側の plain 退避に倒す)。
export function charsOutsideCodeBlocks(text) {
  let outside = 0
  let fence = null   // 開いている囲みの記号 (= 例 '```')、 外なら null
  for (const line of text.split('\n')) {
    const mark = /^ {0,3}(`{3,}|~{3,})/.exec(line)
    if (fence == null) {
      if (mark && !(mark[1][0] === '`' && line.slice(mark[0].length).includes('`'))) fence = mark[1]
      else outside += line.length + 1
    } else if (mark && mark[1][0] === fence[0] && mark[1].length >= fence.length && line.slice(mark[0].length).trim() === '') {
      fence = null
    }
  }
  return outside
}

// markdown を通さず plain text に倒すべき巨大メッセージか。 純関数 (= テスト対象)。
export function isOversizedMessage(text) {
  if (typeof text !== 'string') return false
  if (text.length > PLAIN_FALLBACK_TOTAL_CHARS) return true
  return text.length > PLAIN_FALLBACK_CHARS && charsOutsideCodeBlocks(text) > PLAIN_FALLBACK_CHARS
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

// remark プラグイン (= メモ用): 段落の中の改行と空白を、 書いたとおりに見せる。 改行は改行の印 (= <br>) に、
// 行頭の空白と 2 つ以上続く空白は詰められない空白 (= U+00A0) に替える。 markdown は段落の 2 行目以降の
// 行頭の空白を読む時に落とすので、 文の先頭の階層の段落だけ、 元の文から取り戻す (= リストの続きの字下げは
// 書式なので戻さない)。 取り戻すのは、 元の文との違いが空白だけの時 (= `\*` のような逃がしは読んだ後の値のまま)。
const NBSP = '\u00A0'
const keepSpaces = (line) =>
  line.replace(/^ +/, (m) => NBSP.repeat(m.length)).replace(/ {2,}/g, (m) => NBSP.repeat(m.length))

function remarkAsWritten() {
  return (tree, file) => {
    const source = String(file)
    visit(tree, 'paragraph', (para, _index, parent) => {
      const top = parent?.type === 'root'
      const children = []
      para.children.forEach((node, k) => {
        if (node.type !== 'text') { children.push(node); return }
        let value = node.value
        if (top && node.position) {
          const start = node.position.start.offset
          let raw = source.slice(start, node.position.end.offset)
          // 段落の 1 行目の行頭の空白 (= 3 つまでは段落の書き出しとして落とされる)
          if (k === 0) {
            const lead = source.slice(source.lastIndexOf('\n', start - 1) + 1, start)
            if (/^ +$/.test(lead)) raw = lead + raw
          }
          if (raw !== value && raw.replace(/\s/g, '') === value.replace(/\s/g, '')) value = raw
        }
        value.split('\n').forEach((line, i) => {
          if (i > 0) children.push({ type: 'break' })
          if (line) children.push({ type: 'text', value: keepSpaces(line) })
        })
      })
      para.children = children
    })
  }
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
      // 差し替えた分は飛ばして続ける (= 作ったリンクの中の文字へ降りると、 同じ path がもう一度
      // リンクになって入れ子になり、 1 回のタップで開く処理が 2 回走る)
      return index + parts.length
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

// 画像の出どころ (= `![説明](出どころ)`) を、 画面が読む URL にする純関数 (= テスト対象)。
//   - Mac の path (= 絶対 path、 `~/…`、 `file://…`) は backend の画像の口から読む (= ホームの下だけ・秘密の置き場は
//     拒否・10 MB まで。 画像は記録にも通話にも流れず、 画面が別に取りに行く)
//   - http / https はそのまま
//   - それ以外 (= 相対の path、 data: で埋め込んだ画像) は出さない (= 空文字)。 埋め込みは記録に大きな 1 行を作る
export function imageSource(url) {
  if (typeof url !== 'string' || !url) return ''
  let path = null
  if (url.startsWith('file://')) {
    try { path = decodeURI(url.slice('file://'.length)) } catch { return '' }
  } else if (url.startsWith('~/') || (url.startsWith('/') && !url.startsWith('//'))) {
    path = url
  }
  if (path != null) return apiUrl(`/file/raw?path=${encodeURIComponent(path)}`)
  return /^https?:\/\//i.test(url) ? defaultUrlTransform(url) : ''
}

// 画像の口から読む URL なら、 その Mac の path (= 押した時に file のプレビューで開く)。 違えば null。
function localPathOf(src) {
  const raw = apiUrl('/file/raw?path=')
  return src.startsWith(raw) ? decodeURIComponent(src.slice(raw.length)) : null
}

// url sanitizer は全 render 共通の純関数 (= identity 安定、 memo を壊さない)。
function urlTransform(url, key) {
  // 画像の出どころは imageSource で決める (= Mac の path も読めるようにする)。
  if (key === 'src') return imageSource(url)
  // cpc-file:// は内部で onOpenFile に流す独自スキーム = pass-through。
  // それ以外は react-markdown 既定の sanitizer を使い、 javascript: / data:
  // 等の危険スキームをブロック。 過去ここで `(url) => url` にしてた結果、
  // 任意 URL スキームがそのまま <a href> に出ていた (XSS 経路)。
  if (typeof url === 'string' && url.startsWith('cpc-file://')) return url
  // slack:// は Slack のアプリを開くだけのスキーム (= 押すと OS がアプリへ渡す)。
  if (typeof url === 'string' && /^slack:\/\//i.test(url)) return url
  return defaultUrlTransform(url)
}

// 返事の中の画像。 読めない時は説明の文字を出す。 押すと、 Mac の画像は file のプレビューで、 外の画像は新しいタブで開く。
function MarkdownImage({ src, alt, onOpenFile }) {
  const t = useT()
  const [failed, setFailed] = useState(false)
  if (!src || failed) {
    return <span className="md-image-missing">🖼 {alt || t('markdown.image_missing')}</span>
  }
  const local = localPathOf(src)
  const open = () => {
    if (local != null) onOpenFile(local)
    else window.open(src, '_blank', 'noreferrer')
  }
  return <img className="md-image" src={src} alt={alt || ''} loading="lazy" onError={() => setFailed(true)} onClick={open} />
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
      // slack:// は同じタブのまま OS に渡す (= 新しいタブにすると、 アプリが開いた後に空のタブが残る)。
      if (/^slack:\/\//i.test(href || '')) return <a href={href}>{children}</a>
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
    img({ src, alt }) {
      return <MarkdownImage src={src} alt={alt} onOpenFile={onOpenFile} />
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

// asWritten = メモの描き方: 長さで畳まず (= 素の文へ退くこともしない)、 段落の改行と空白を書いたとおりに残す。
const MessageRenderer = React.memo(function MessageRenderer({ text, onOpenFile, streaming, asWritten }) {
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
    () => (streaming ? [remarkGfm] : asWritten ? [remarkGfm, remarkAsWritten, remarkFilePaths] : [remarkGfm, remarkFilePaths]),
    [streaming, asWritten],
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
  if (!asWritten && isOversizedMessage(text)) {
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
  if (!asWritten && isCollapsibleMessage(deferredText)) {
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
