// 設定の画面の card が持つ入力 (draft)。 backend が持つ値 (signature) が変わった時だけ、 入力を新しい値に取り直す
// (= 保存した後に、 保存した値を入力に写す。 別の card の保存や読み直しでは、 入力の途中の欄を消さない)。
import { useState } from 'react'

/** → [draft, setDraft]。 initial = backend の今の値から作った入力、 signature = その値を表す文字列。 */
export function useDraft(initial, signature) {
  const [draft, setDraft] = useState(initial)
  const [seen, setSeen] = useState(signature)
  if (seen !== signature) {
    setSeen(signature)
    setDraft(initial)
  }
  return [draft, setDraft]
}
