// tool handler 群が共有する定数 + 文字列切り詰め helper。
// SHORT_LABEL_MAX は折りたたみサマリ用の上限文字数 (= summary 1 行に出す省略表示)、
// truncate は超過分を末尾 … で潰す。
export const SHORT_LABEL_MAX = 60

export function truncate(str, max = SHORT_LABEL_MAX) {
  if (!str) return ''
  return str.length > max ? str.slice(0, max) + '…' : str
}
