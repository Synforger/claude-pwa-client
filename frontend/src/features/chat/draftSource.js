// 入力欄が今持っている打ちかけの文 (= まだ親の input へ書き戻していない分) を、 保存の側から読む口。
//
// ChatInput は打鍵を自分の中に持ち、 親へ書き戻すのはタブを切り替えた時と送信の時だけ
// (= 1 文字ごとにアプリ全体を描き直さないため)。 頁を離れる時の保存 (= useChatStorage) が
// 親の input だけを見ると、 打っている最中の文が保存から漏れ、 読み込み直しで消える。
// 保存を書くのは useChatStorage 1 か所のまま、 ここで最新の打ちかけを渡す。
let source = null

// source: () => ({ sid, text }) | null
export function setDraftSource(fn) { source = fn }

export function currentDraft() {
  try { return source ? source() : null } catch { return null }
}
