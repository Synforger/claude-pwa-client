// 設定の画面の card が「保存していない変更がある」 を画面に知らせる口。 画面は 1 つでも在る間、 閉じる前に捨ててよいかを訊く。
import { createContext, useContext, useLayoutEffect } from 'react'

export const DirtyContext = createContext(() => {})

/** card が変えたまま (= 保存していない、 不正な入力も含む) かを画面へ知らせる。 card が消える時は、 変更なしに戻す。
 * The report is settled with the render (a layout effect): reported after paint, it reaches the screen after the
 * "saved" note shows, and closing in between asks whether to discard a change that was saved. */
export function useReportDirty(id, dirty) {
  const report = useContext(DirtyContext)
  useLayoutEffect(() => {
    report(id, dirty)
    return () => report(id, false)
  }, [report, id, dirty])
}
