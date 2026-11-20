// チャットに出る client の封筒の発話 (別のタブからの伝言・票の連絡・自動の入れ替え・階層のタブの最初の発話・
// client の知らせ) を、 道具の行 / system の知らせ (SystemNoteCard) と同じ形の 1 行にする部品。
// MessageItem の 5 つの分岐が呼ぶ。 行の頭の印は 3 通り: 開く中身がある行は ▸ / ▾、 押すと票の画面が開く行は ↗、
// 中身の無い行は ·。 開閉はこの部品の中だけで持ち、 保存しない (= 既定は畳む)。
import { useState } from 'react'
import './EnvelopeLine.css'

const MARK_FOLDED = '▸'
const MARK_UNFOLDED = '▾'
const MARK_LINK = '↗'
const MARK_PLAIN = '·'

/** 本文の頭の、 空でない 1 行 (= 畳んだ行に添える)。 無ければ空文字。 */
export function firstFilledLine(text) {
  const line = text.split('\n').find((l) => l.trim() !== '')
  return line ? line.trim() : ''
}

// 1 行の中身: 印・アイコン・見出し・(あれば) 見出しに続く語。
function LineText({ mark, icon, label, labelTestId, tail, tailTestId, tailSeparator }) {
  return (
    <>
      <span className="tool-marker" aria-hidden="true">{mark}</span>
      {icon && <span aria-hidden="true">{icon} </span>}
      <span data-testid={labelTestId}>{label}</span>
      {tail && <>{tailSeparator}<span data-testid={tailTestId}>{tail}</span></>}
    </>
  )
}

function FoldedEnvelopeLine({ body, bodyTestId, toggleTestId, tail, ...text }) {
  const [open, setOpen] = useState(false)
  return (
    <details className="envelope-line" open={open}>
      {/* details の自前の開閉は使わず、 state で開閉する (= 開いた時だけ中身を描くため) */}
      <summary
        className="tool-line envelope-head"
        aria-expanded={open}
        data-testid={toggleTestId}
        onClick={(event) => { event.preventDefault(); setOpen((value) => !value) }}
      >
        {/* 開いた時は本文が見えるので、 見出しに添えた本文の頭は外す */}
        <LineText mark={open ? MARK_UNFOLDED : MARK_FOLDED} tail={open ? null : tail} {...text} />
      </summary>
      {open && <div className="envelope-body" data-testid={bodyTestId}>{body}</div>}
    </details>
  )
}

function LinkEnvelopeLine({ onOpen, openTestId, ...text }) {
  return (
    <button type="button" className="tool-line envelope-head envelope-link" onClick={onOpen} data-testid={openTestId}>
      <LineText mark={MARK_LINK} {...text} />
    </button>
  )
}

/**
 * 封筒の発話の 1 行。 `body` があれば押して開く行、 `onOpen` があれば押すと `onOpen` を呼ぶ行 (= 票の画面を開く)、
 * どちらも無ければ中身の無い行になる。 `tail` は見出しの後に `tailSeparator` を挟んで続ける語 (= 伝言の本文の頭、 階層の名前)。
 * `toggleTestId` (開閉の行)・`bodyTestId` (開いた時だけ在る中身)・`openTestId` (押すと開く行)・`labelTestId`・`tailTestId` は試験の目印。
 */
export function EnvelopeLine({ icon, label, labelTestId, tail, tailTestId, tailSeparator = ' · ', body, bodyTestId, toggleTestId, onOpen, openTestId }) {
  const text = { icon, label, labelTestId, tail, tailTestId, tailSeparator }
  if (onOpen) return <LinkEnvelopeLine onOpen={onOpen} openTestId={openTestId} {...text} />
  if (body) return <FoldedEnvelopeLine body={body} bodyTestId={bodyTestId} toggleTestId={toggleTestId} {...text} />
  return (
    <div className="tool-line envelope-head envelope-plain">
      <LineText mark={MARK_PLAIN} {...text} />
    </div>
  )
}
