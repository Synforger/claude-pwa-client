// 言い方の印 (= 文頭の `[名前]`。 値を添えた `[名前 i=1.2 s=1.1]` も) を、 表示する文から外す。
//
// 印は声への指定で、 読む人に向けた文ではない。 声の側 (= backend/core/speech.py) は印を剥がしてから
// 音にする。 表示も同じ所の印だけを外す: 行の頭 (= 見出し・箇条書き・引用の記号の後) と、 文の終わり
// (= 句点・感嘆符・疑問符) の直後。 文の途中の `[名前]` と、 一覧に無い名前の `[…]` は文として残す。
// コードブロックとインラインのコードの中は触らない。 外すのは表示だけで、 記録の文は変えない。

const LEAD = String.raw`\s*(?:>+\s*)*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)?`
const STOP = String.raw`[。！？!?]+[」』）)】]*`
const GAP = '[ \\t\\u3000]*'   // 半角の空白・tab・全角の空白
const FENCE = /^\s*(```|~~~)/
const CODE = /(`[^`]*`)/
// 印に添える値 (= `i=1.2`。 名前と範囲は声の側が見る。 表示から外すのは形だけで決める)
const VALUE = String.raw`(?:\s+[A-Za-z]+=[-+]?(?:\d+(?:\.\d*)?|\.\d+))*\s*`

// marks = その agent の印の名前の一覧。 無ければ文をそのまま返す。
export function hideMarks(text, marks) {
  if (typeof text !== 'string' || !text || !Array.isArray(marks)) return text
  const names = marks.filter(name => /^[A-Za-z]+$/.test(name))
  if (!names.length) return text
  const mark = String.raw`\[(?:${names.join('|')})${VALUE}\]`
  const atHead = new RegExp(`^(${LEAD})${mark}${GAP}`)
  const afterStop = new RegExp(`(${STOP}${GAP})${mark}${GAP}`, 'g')
  let fenced = false
  return text.split('\n').map((line) => {
    if (FENCE.test(line)) { fenced = !fenced; return line }
    if (fenced) return line
    return line.split(CODE).map((part, i) => {
      if (part.startsWith('`')) return part
      const shown = i === 0 ? part.replace(atHead, '$1') : part
      return shown.replace(afterStop, '$1')
    }).join('')
  }).join('\n')
}
