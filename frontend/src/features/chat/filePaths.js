// 文の中の file の path を見つける規則 (= チャットとメモで 1 つ)。 path はタップでプレビューに開く。
//
// path = `~/` か、 Mac の利用者の folder の絶対 path で始まり、 空白・引用符・閉じ括弧・backtick の手前まで。
const PATH_BODY = String.raw`~\/[^\s` + '`' + String.raw`"')\]]+|\/Users\/[^\s` + '`' + String.raw`"')\]]+`

// markdown の文の中で探す時の規則。 リンクの `(…)` と inline code の中は除く (= inline code は
// 別に丸ごとリンクにする)。
export const MARKDOWN_PATH_RE = new RegExp(String.raw`(?<![(` + '`' + `])(${PATH_BODY})`, 'g')

// 書いたとおりの文 (= markdown として読まない) を、 地の文と path に割る。
// 返り値 = [{ text } | { path }] (= 並びは元の文の順、 つなげると元の文に戻る)。
export function splitPaths(text) {
  const re = new RegExp(`(${PATH_BODY})`, 'g')
  const parts = []
  let last = 0
  let match
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) parts.push({ text: text.slice(last, match.index) })
    parts.push({ path: match[0] })
    last = match.index + match[0].length
  }
  if (last < text.length) parts.push({ text: text.slice(last) })
  return parts
}
