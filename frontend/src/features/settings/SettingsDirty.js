// 設定の画面の card が「保存していない変更がある」 を画面に知らせる口。 画面は 1 つでも在る間、 閉じる前に捨ててよいかを訊く。
import { createContext, useContext, useEffect } from 'react'

export const DirtyContext = createContext(() => {})

/** card が変えたまま (= 保存していない、 不正な入力も含む) かを画面へ知らせる。 card が消える時は、 変更なしに戻す。 */
export function useReportDirty(id, dirty) {
  const report = useContext(DirtyContext)
  useEffect(() => {
    report(id, dirty)
    return () => report(id, false)
  }, [report, id, dirty])
}
