import { memo, useEffect, useMemo, useState } from 'react'
import MessageRenderer from './MessageRenderer.jsx'
import AskUserQuestionBubble from '../ask-user-question/AskUserQuestionBubble.jsx'
import AttachedImages from '../attachments/AttachedImages.jsx'
import { getEntry as getMessageEntry } from '../../registry/messageRegistry.js'
import { formatToolResultContent, formatDuration, formatModelName, formatTokens } from '../../utils/format.js'
import { diffLines, compactDiff } from '../../utils/diff.js'
import { apiFetch } from '../../utils/api.js'
import { useT } from '../../i18n/t.js'
import './MessageItem.css'

const RESULT_PREVIEW_CHARS = 800

// 🧩 タップ時に「どこを開くか」 のスコープ記述子を作る。
//   - Task     : input.description が subagent meta.description と一致 → その agent transcript
//   - Workflow : tool_result の "Task ID: <taskId>" が manifest.taskId と一致 → その run
// 引き当てキーが取れなければ null (= パネルをスコープ無しで開く)。
function subagentFocus(t) {
  if (t.name === 'Task' && t.subagentDescription) {
    return { kind: 'agentDesc', value: t.subagentDescription }
  }
  if (t.name === 'Workflow' && t.result) {
    const text = formatToolResultContent(t.result.content) || ''
    const m = text.match(/Task ID:\s*(\S+)/)
    if (m) return { kind: 'workflowTaskId', value: m[1] }
  }
  return null
}

// Grep / Glob の結果本文をパスリンク化する。
// Grep content mode: "path:line:content" / files_with_matches: "path"
// Glob: "path" (絶対 or 相対)
// パス判定ゆるめ: 先頭から [:\s] までを path と仮定し、/ を含むか拡張子っぽいものだけリンク化。
function LinkifiedResult({ text, onOpenFile, errorClass }) {
  const lines = text.split('\n')
  return (
    <pre className={`tool-result-text ${errorClass || ''}`}>
      {lines.map((line, i) => {
        // 行頭のパス部分を抽出: 空白とコロンで切る
        const m = line.match(/^([^\s:]+)(.*)$/)
        if (!m) return <div key={i}>{line || ' '}</div>
        const [, pathCandidate, rest] = m
        const looksLikePath = pathCandidate.includes('/') || /\.[a-zA-Z0-9]{1,6}$/.test(pathCandidate)
        if (!looksLikePath || !onOpenFile) {
          return <div key={i}>{line || ' '}</div>
        }
        return (
          <div key={i}>
            <span className="file-link" onClick={() => onOpenFile(pathCandidate)}>{pathCandidate}</span>
            {rest}
          </div>
        )
      })}
    </pre>
  )
}

// Edit の場合、編集後のファイル本体を取得して new_string の開始行 (1-indexed) を返す。
// 取れない / 見つからない場合は null を返す（呼び出し側で relative=1 fallback）。
//
// 結果はモジュールレベルでキャッシュする。 DiffView の useEffect 依存はプリミティブ固定済み
// (2026-07-21) だが、 タブ切替で ChatPanel の中身が入れ替わると Edit 行ごと mount し直され、
// effect が毎回 /file を素取得していた (2026-07-27 実測: タブ 5 枚運用で同一ファイルへ
// 475 回/時 → 端末発熱・通信の主犯)。 確定済み Edit の基準行は「その編集内容がファイルの
// どこに居るか」 なので、 一度取れた値はセッション中変わらない前提で保持してよい。
// ファイル取得自体の失敗 (ネットワーク / abort) はキャッシュしない (= 次の mount で再試行)。
const editBaseLineCache = new Map()
const EDIT_BASELINE_CACHE_MAX = 500

// ファイル本体は path 単位で持つ (= 基準行キャッシュとは別レイヤ)。 1 つのファイルを複数回
// 編集したターンでは Edit 行の数だけ別キーになるので、 基準行キャッシュだけでは同じファイルを
// 人数分取りに行っていた。 2026-08-03 実測: タブ表示 1 回で同一ファイルへ最大 7 重複、
// 全体で 314 リクエスト中ユニークは 70 (= 4.5 倍の無駄取得)。
const fileContentCache = new Map()
const FILE_CONTENT_CACHE_MAX = 100
// 進行中の取得 (= path → Promise)。 同じファイルへの同時要求を 1 本に畳む。
const inflightFileFetches = new Map()

function fetchFileContent(filePath) {
  if (fileContentCache.has(filePath)) return Promise.resolve(fileContentCache.get(filePath))
  const inflight = inflightFileFetches.get(filePath)
  if (inflight) return inflight
  // AbortSignal は **渡さない**。 待ち手を共有するので、 1 つの Edit 行が unmount した
  // だけで取得ごと中断すると、 他の待ち手まで空振りしてキャッシュが埋まらない。 旧実装は
  // 各行が自分の signal 付きで取りに行っていたため、 タブを素早く切り替えると abort →
  // 未キャッシュ → 次の表示でまた全件取得、 を繰り返していた。
  const p = apiFetch(`/file?path=${encodeURIComponent(filePath)}`)
    .then(res => (res.ok ? res.json() : null))
    .then(data => {
      const content = data?.content
      if (typeof content !== 'string') return null
      if (fileContentCache.size >= FILE_CONTENT_CACHE_MAX) fileContentCache.clear()
      fileContentCache.set(filePath, content)
      return content
    })
    .catch(() => null)
    .finally(() => inflightFileFetches.delete(filePath))
  inflightFileFetches.set(filePath, p)
  return p
}

export async function fetchEditBaseLine(filePath, newString, signal) {
  if (!filePath || !newString) return null
  // 区切りは NUL (= path に現れ得ない文字)。 生の NUL を書くと file 自体が binary 判定になり
  // grep / 検出機構が本 file を丸ごと skip するので escape で書く。
  const cacheKey = `${filePath}\0${newString.length}:${newString.slice(0, 200)}`
  if (editBaseLineCache.has(cacheKey)) return editBaseLineCache.get(cacheKey)
  const content = await fetchFileContent(filePath)
  // 取得中に呼び出し側が消えていたら結果を捨てる (= 取得自体は完了させてキャッシュに残す)
  if (signal?.aborted) return null
  if (content == null) return null
  const idx = content.indexOf(newString)
  // idx < 0 (= その後の編集で new_string が消えた) も確定結果としてキャッシュする。
  // ここを再試行にすると「見つからないファイル」 が mount のたびに再取得され続ける。
  let line = null
  if (idx >= 0) {
    // idx 以前の \n 数 + 1 = 開始行番号 (1-indexed)
    line = 1
    for (let i = 0; i < idx; i++) if (content.charCodeAt(i) === 10) line++
  }
  if (editBaseLineCache.size >= EDIT_BASELINE_CACHE_MAX) editBaseLineCache.clear()
  editBaseLineCache.set(cacheKey, line)
  return line
}

// ops (compactDiff 済み) を走査して、各行に old/new 行番号を付ける。
function annotateLineNumbers(ops, baseLine) {
  let oldNum = baseLine
  let newNum = baseLine
  return ops.map(op => {
    if (op.type === 'gap') {
      const skip = op.skippedLines || 0
      oldNum += skip
      newNum += skip
      return { ...op, oldNum: null, newNum: null }
    }
    if (op.type === 'del') {
      const n = { ...op, oldNum, newNum: null }
      oldNum++
      return n
    }
    if (op.type === 'add') {
      const n = { ...op, oldNum: null, newNum }
      newNum++
      return n
    }
    // ctx
    const n = { ...op, oldNum, newNum }
    oldNum++
    newNum++
    return n
  })
}

function formatLineNum(n) {
  if (n == null) return ''
  return String(n)
}

function DiffView({ diffInput }) {
  const t = useT()
  const [baseLine, setBaseLine] = useState(null)
  const [baseKnown, setBaseKnown] = useState(false)

  // 依存はプリミティブ (= file_path / new_string) に固定する。 diffInput オブジェクトを
  // deps にすると、 streaming 中に上流で message が再生成されて diffInput の参照だけ変わる
  // たびに /file を再 fetch してしまう (= 確定済み Edit でも毎 render fetch する storm、
  // 2026-07-21 実測: 同一ファイルを 150ms 内に 4 回取得 → 端末発熱)。 実際に取得内容が
  // 変わるのは file_path / new_string が変わった時だけ。
  const editFilePath = diffInput?.kind === 'edit' ? diffInput.file_path : null
  const editNewString = diffInput?.kind === 'edit' ? diffInput.new_string : null
  useEffect(() => {
    if (!editFilePath) return
    const ctrl = new AbortController()
    fetchEditBaseLine(editFilePath, editNewString, ctrl.signal)
      .then(line => {
        setBaseLine(line)
        setBaseKnown(true)
      })
    return () => ctrl.abort()
  }, [editFilePath, editNewString])

  // LCS は重いので diff 内容単位でキャッシュ。 deps も old/new 文字列 (= プリミティブ) に
  // 固定し、 diffInput 参照の churn では recompute しない (= 大きな Edit/Write で main
  // thread が固まらない + streaming 中の再計算 storm を防ぐ)。
  const diffKind = diffInput?.kind
  const diffOld = diffInput?.old_string
  const diffNew = diffInput?.new_string
  const rawOps = useMemo(() => {
    if (diffKind !== 'edit') return null
    return compactDiff(diffLines(diffOld, diffNew), 2)
  }, [diffKind, diffOld, diffNew])

  if (!diffInput) return null

  if (diffInput.kind === 'edit') {
    const effectiveBase = baseLine ?? 1
    const isRelative = baseLine == null
    const ops = annotateLineNumbers(rawOps, effectiveBase)
    // path は summary に出てるので冗長。replace_all フラグ or 行番号相対注記があるときだけヘッダを出す
    const showHeader = diffInput.replace_all || (baseKnown && isRelative)
    return (
      <div className="diff-view">
        {showHeader && (
          <div className="diff-path">
            {diffInput.replace_all && <span>replace_all</span>}
            {baseKnown && isRelative && <span className="diff-path-note">{t('diff.relative_lines')}</span>}
          </div>
        )}
        <pre className="diff-body">
          {ops.map((op, i) => (
            <div key={i} className={`diff-line ${op.type}`}>
              <span className="diff-lineno diff-lineno-old">{formatLineNum(op.oldNum)}</span>
              <span className="diff-lineno diff-lineno-new">{formatLineNum(op.newNum)}</span>
              <span className="diff-marker">{op.type === 'add' ? '+' : op.type === 'del' ? '-' : op.type === 'gap' ? '…' : ' '}</span>
              <span className="diff-text">{op.type === 'gap' ? '' : op.text}</span>
            </div>
          ))}
        </pre>
      </div>
    )
  }
  // write: 新規作成扱いで全行を + で。行番号は 1 始まり
  if (diffInput.kind === 'write') {
    const lines = String(diffInput.content ?? '').split('\n')
    if (lines.length > 0 && lines[lines.length - 1] === '' && diffInput.content.endsWith('\n')) lines.pop()
    return (
      <div className="diff-view">
        <div className="diff-path"><span>new file</span></div>
        <pre className="diff-body">
          {lines.map((line, i) => (
            <div key={i} className="diff-line add">
              <span className="diff-lineno diff-lineno-old"></span>
              <span className="diff-lineno diff-lineno-new">{i + 1}</span>
              <span className="diff-marker">+</span>
              <span className="diff-text">{line}</span>
            </div>
          ))}
        </pre>
      </div>
    )
  }
  return null
}

// 通常完了 (end_turn / tool_use) 以外の停止理由をチップで強調表示
const STOP_REASON_LABELS = {
  // stop_reason label は t() で動的引き。 直接 t() をここに書けないので i18n key を持たせ
  // 描画時に t(labelKey) する形にする (= フックの再 render で言語切替に追随)。
  max_tokens: { labelKey: 'message.stop.max_tokens', cls: 'warn' },
  refusal: { labelKey: 'message.stop.refusal', cls: 'danger' },
  pause_turn: { labelKey: 'message.stop.pause_turn', cls: 'info' },
  model_context_window_exceeded: { labelKey: 'message.stop.model_context_window_exceeded', cls: 'warn' },
}

// 4.8 の refusal は stop_details に理由を持つ。 shape は string / {reason|message|type} の
// いずれもあり得るので防御的に読めるものを拾う。
function stopDetailText(details) {
  if (!details) return ''
  if (typeof details === 'string') return details
  if (typeof details === 'object') {
    return details.reason || details.message || details.description || details.type || ''
  }
  return ''
}

function StopReasonChip({ meta, streaming }) {
  const t = useT()
  if (!meta || streaming) return null
  if (meta.is_error) {
    const detail = stopDetailText(meta.stop_details)
    const label = meta.stop_reason ? ` (${meta.stop_reason})` : ''
    return (
      <div className="stop-chip danger">
        {t('message.stop.error_prefix')}{label}{detail ? `: ${detail}` : ''}
      </div>
    )
  }
  if (!meta.stop_reason || meta.stop_reason === 'end_turn' || meta.stop_reason === 'tool_use') return null
  const def = STOP_REASON_LABELS[meta.stop_reason]
  if (!def) return <div className="stop-chip info">⚠ {meta.stop_reason}</div>
  return <div className={`stop-chip ${def.cls}`}>{t(def.labelKey)}</div>
}

function MetaLine({ meta, streaming, trailing }) {
  if (!meta || streaming) {
    // meta がまだ無い (= streaming 等) でも、 fork ボタンだけは出したい時がある
    return trailing ? <div className="bubble-meta">{trailing}</div> : null
  }
  const parts = []
  // cost 表示は退役 (2026-07-27)。 表示条件だった apiKeySource は旧 SDK の system/init event
  // 由来で、 現行 harness の jsonl には来ない (= 供給が物理的に無い)。 subscription 経路では
  // cost は参考値で誤解を招くため非表示、 という元の設計意図とも整合する。
  const tokens = formatTokens(meta.usage)
  if (tokens) parts.push(tokens)
  // turns は意味が伝わりにくいので非表示
  const dur = formatDuration(meta.duration_ms)
  if (dur) parts.push(dur)
  const model = formatModelName(meta.modelUsage)
  if (model) parts.push(model)
  if (parts.length === 0 && !trailing) return null
  return (
    <div className="bubble-meta">
      {/* fork ボタンはメタ行の先頭 (= 一番左、 in/cache より前) に置く。 エージェント回答の
          本命操作なので最初に目に入る位置に。 */}
      {trailing && <>{trailing}{parts.length > 0 ? ' ' : ''}</>}
      {/* メタ本文は淡く。 opacity を本文 span に閉じることで、 隣の fork は親 opacity に
          引きずられず明るく出せる。 */}
      {parts.length > 0 && <span className="bubble-meta-parts">{parts.join(' · ')}</span>}
    </div>
  )
}

const MessageItem = memo(function MessageItem({ msg, onOpenFile, activeSubagentTool, runningSubagents, onOpenSubagents, onFork }) {
  const t = useT()
  // system kind は messageRegistry に「fromEvent + Render」 ペアで集約しており、
  // ここでは generic lookup で表示コンポーネントを引くだけ (= F-04 consumer)。
  // 新しい system kind を増やす時は messageRegistry に Render を 1 個足すだけで配線完了、
  // この switch を膨らませる必要は無い。
  if (msg.role === 'system') {
    const entry = getMessageEntry(msg.kind)
    if (entry && entry.Render) {
      const Render = entry.Render
      return <Render msg={msg} />
    }
    // 未知 kind は安全側に倒して何も描画しない (= 旧実装も該当 if が無ければ素通りで
    // 下の通常分岐に落ちて空 message を出していたが、 system は通常分岐に乗らない方が
    // 安全。 万が一 build 側が registry 未登録 kind を投げ込んだ場合は黙って捨てる)。
    return null
  }
  if (msg.role === '__loading__') {
    return (
      <div className="message agent">
        <span className="bubble dim">{t('chat.thinking')}</span>
      </div>
    )
  }
  // streaming 中で中身がまだゼロ (送信直後〜最初のチャンク到着まで) は「推論中…」を出して
  // 沈黙を埋める。最初のチャンクが届いた瞬間にこの分岐から抜けて通常描画へ移行する。
  if (
    msg.role === 'agent' &&
    msg.streaming &&
    !msg.text &&
    !msg.thinking &&
    !msg.askUserQuestion &&
    !(msg.tools && msg.tools.length > 0)
  ) {
    return (
      <div className="message agent">
        <span className="bubble dim">{t('chat.thinking')}</span>
      </div>
    )
  }
  // フォーク (= 会話分岐) の起点にできる切れ目だけにボタンを出す。 assistant の純テキスト回答
  // (= tool_use を保留してない、 質問待ちでない) のみ許可、 user 発言からは出さない (= 2026-06-30
  // 利用者要望、 自分の発言を fork 起点にする UX 価値が薄く agent 応答後に fork 判断する流れに統一)。
  // meta.stop_reason は result が最後のバブルに上書き stamp するため当てにならないので使わず、
  // バブルが tool / 質問待ちを持たない (= 純テキスト回答) ことで判定する。 最終判定は backend。
  const canForkAgent =
    msg.role === 'agent' && !msg.streaming && msg.uuid &&
    !(msg.tools?.length > 0) && !msg.askUserQuestion
  const forkButton = onFork && canForkAgent ? (
    <button
      type="button"
      className="bubble-fork"
      onClick={() => onFork(msg.uuid)}
      title="Fork the conversation from this message into a new tab"
      data-testid="fork-button"
    >
      ⑂ fork
    </button>
  ) : null
  // agent 回答はモデル名と同じメタ行に同居させる。
  const agentForkBtn = forkButton

  return (
    <div
      className={`message ${msg.role}`}
      data-testid={`message-bubble-${msg.role}`}
      data-cpc-role={msg.role}
      data-cpc-uuid={msg.uuid || ''}
      data-cpc-optimistic={msg.optimistic ? '1' : '0'}
      data-cpc-ts={typeof msg.ts === 'number' ? msg.ts : ''}
    >
      {msg.role === 'user' && (msg.imageRefs?.length > 0 || msg.imageUrls?.length > 0 || msg.fileNames?.length > 0) ? (
        <div className="user-block">
          <AttachedImages imageRefs={msg.imageRefs} imageUrls={msg.imageUrls} />
          {msg.fileNames?.length > 0 && (
            <div className="attach-files">
              {msg.fileNames.map((name, j) => (
                <span key={j} className="file-chip">📄 {name}</span>
              ))}
            </div>
          )}
          {msg.text && (
            <span className="bubble">
              <MessageRenderer text={msg.text} onOpenFile={onOpenFile} streaming={msg.streaming} />
            </span>
          )}
        </div>
      ) : msg.role === 'agent' && (msg.tools?.length > 0 || msg.thinking || msg.askUserQuestion) ? (
        <div className="agent-block">
          {msg.thinking && (
            <details className="thinking-block">
              <summary>💭 thinking</summary>
              <pre className="thinking-text">{msg.thinking}</pre>
            </details>
          )}
          {/* 2026-06-22: 旧実装は tools → text 順だったが、 claude の実応答は
              「説明テキスト → Bash 等の tool 実行」 の流れが大半。 順序逆転で「Bash の後に
              そのことを説明するメッセージが出る」 ように見えるバグになっていた。 text を
              先に描画して実応答順に揃える。 */}
          {msg.text && (
            <span className="bubble">
              <MessageRenderer text={msg.text} onOpenFile={onOpenFile} streaming={msg.streaming} />
            </span>
          )}
          {msg.tools?.length > 0 && (
            <div className="tool-log">
              {msg.tools.map((tool) => {
                const resultText = tool.result ? formatToolResultContent(tool.result.content) : null
                // 文字数ラベルの真値。 履歴 GET は巨大な tool_result を preview に切り詰めて
                // 元の文字数を full_chars で寄越すので、 有ればそれを使う (= 切り詰めても
                // 「· 384,200 文字」 が正しく出る、 2026-07-27)。
                const resultChars = typeof tool.result?.full_chars === 'number'
                  ? tool.result.full_chars
                  : (resultText?.length ?? 0)
                const truncated = resultText && (resultChars > RESULT_PREVIEW_CHARS)
                const hasDiff = !!tool.diffInput
                // Read はパスが summary に出てるので input の echo は冗長。tool-input-full は描画しない
                const showInputFull = !hasDiff && tool.name !== 'Read' && tool.shortLabel && tool.shortLabel !== tool.label
                // Edit/Write 成功時の "File updated successfully" みたいな確認文は冗長 (diff が見えてれば自明)。
                // エラー時は原因が書かれてるので表示する。
                const suppressSuccessResult = hasDiff && tool.result && !tool.result.is_error
                const showResult = !!tool.result && !suppressSuccessResult
                const hasMore = hasDiff || showInputFull || showResult
                // 過去メッセージのスクロールバック中に diff / 結果が大きく開きっぱなしだと
                // 読みにくいので、 デフォルトは全部閉じる。 必要な時だけタップで展開する。
                const openByDefault = false
                return (
                  <details
                    key={tool.id}
                    className={`tool-block ${tool.result?.is_error ? 'is-error' : ''}`}
                    open={openByDefault}
                  >
                    <summary className={`tool-line tool-${tool.name.toLowerCase()}`} title={tool.label}>
                      <span className="tool-marker">{hasMore ? '▸' : '·'}</span>
                      <span className="tool-short">{tool.shortLabel || tool.label}</span>
                      {tool.result?.is_error && <span className="tool-err-mark"> ⚠</span>}
                      {resultText && showResult && (
                        <span className="tool-meta"> · {t('tool.chars', { n: resultChars })}</span>
                      )}
                      {/* Task tool が進行中 (= result 未受信) でかつ status.subagent が active なら、
                          subagent 内で今動いてる sub-tool 名を inline 併記する。 これで「Task が
                          何をやってるか」 が普通の tool 行として観察可能 (= ActivityBar 撤去の代替)。 */}
                      {tool.name === 'Task' && !tool.result && activeSubagentTool && (
                        <span className="tool-meta"> · ↳ {activeSubagentTool}</span>
                      )}
                      {/* Task / Workflow は子エージェントを生やす。 タイムライン上のこの地点から
                          🧩 (= サブエージェント一覧) へ飛べるようにする (= 「どこで分岐したか」 を
                          残しつつ、 中身は専用パネルで深掘り)。 details の開閉とは別操作にするため
                          preventDefault + stopPropagation。 */}
                      {(tool.name === 'Task' || tool.name === 'Workflow') && onOpenSubagents && (
                        <button
                          type="button"
                          className="tool-open-subagents"
                          onClick={(e) => { e.preventDefault(); e.stopPropagation(); onOpenSubagents(subagentFocus(t)) }}
                          title={t('message.tool.open_subagents')}
                        >
                          🤖{(!tool.result || (runningSubagents && t.subagentDescription && runningSubagents.has(t.subagentDescription))) && <span className="tool-running-dot" />}
                        </button>
                      )}
                    </summary>
                    {hasMore && (
                      <div className="tool-body">
                        {hasDiff ? (
                          <DiffView diffInput={tool.diffInput} />
                        ) : showInputFull && (
                          <pre className="tool-input-full">{tool.label}</pre>
                        )}
                        {showResult && (() => {
                          const shown = truncated ? resultText.slice(0, RESULT_PREVIEW_CHARS) + t('message.tool.result_truncated_suffix') : resultText
                          const errorClass = tool.result.is_error ? 'is-error' : ''
                          if ((tool.name === 'Grep' || tool.name === 'Glob') && !tool.result.is_error) {
                            return <LinkifiedResult text={shown} onOpenFile={onOpenFile} errorClass={errorClass} />
                          }
                          return (
                            <pre className={`tool-result-text ${errorClass}`}>
                              {shown}
                            </pre>
                          )
                        })()}
                      </div>
                    )}
                  </details>
                )
              })}
              {msg.streaming && <div className="tool-line tool-pending">…</div>}
            </div>
          )}
          {msg.askUserQuestion && (
            <AskUserQuestionBubble
              key={msg.askUserQuestion.tool_use_id}
              askUserQuestion={msg.askUserQuestion}
            />
          )}
          <StopReasonChip meta={msg.meta} streaming={msg.streaming} />
          <MetaLine meta={msg.meta} streaming={msg.streaming} trailing={agentForkBtn} />
        </div>
      ) : msg.role === 'agent' ? (
        <div className="agent-block">
          {msg.text && (
            <span className="bubble">
              <MessageRenderer text={msg.text} onOpenFile={onOpenFile} streaming={msg.streaming} />
            </span>
          )}
          <StopReasonChip meta={msg.meta} streaming={msg.streaming} />
          <MetaLine meta={msg.meta} streaming={msg.streaming} trailing={agentForkBtn} />
        </div>
      ) : (
        <span className="bubble">
          <MessageRenderer text={msg.text} onOpenFile={onOpenFile} streaming={msg.streaming} />
        </span>
      )}
      {/* 送信失敗 (= backend で JSONL user 行 +1 を確認できず、 再送 1 回も届かなかった)
          の表示。 text は input box に復元されているのでユーザは送り直せる。 */}
      {msg.role === 'user' && msg.sendFailed && (
        <div className="send-failed-note" style={{ color: '#c0392b', fontSize: '0.85em', marginTop: 4 }}>
          ⚠ Not delivered to claude — text restored in the input box
        </div>
      )}
    </div>
  )
}, areEqual)

// custom equality (= 2026-06-23 perf sweep)。 default shallow と同等の比較を明示し、
// 将来 props 追加時の memo skip 漏れを抑える。 activeSubagentTool は subagent ライブ表示で
// streaming 中ですら ほぼ不変 (= tool 切替時のみ変化) なので、 ここで早期 skip すれば
// MessageRenderer の markdown 再 parse を全件抑えられる。 msg 参照 + callback 参照 + 軸 props
// のみ比較。 onFork は activeSid 切替時にしか変わらないので参照比較で十分。
function areEqual(prev, next) {
  return (
    prev.msg === next.msg
    && prev.onOpenFile === next.onOpenFile
    && prev.activeSubagentTool === next.activeSubagentTool
    && prev.runningSubagents === next.runningSubagents
    && prev.onOpenSubagents === next.onOpenSubagents
    && prev.onFork === next.onFork
  )
}

export default MessageItem
