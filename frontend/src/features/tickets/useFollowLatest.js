// 票の画面を、 チャットと同じ「最新の所で開き、 届いたら付いていき、 上へ送って読んでいる間は引き戻さない」 形にする hook。
// 張り付きの判定はチャットと同じ部品 (= chat/stickToBottom.js の nextStuck と、 最下端へ飛ぶ jumpToBottom) を使う。 呼ぶのは TicketView。

import { useCallback, useEffect, useLayoutEffect, useRef } from 'react'
import { jumpToBottom, nextStuck } from '../chat/stickToBottom.js'

/**
 * 送る容器の ref と onScroll を返す。 `ticketId` が変わると張り付きに戻って最下端へ飛び、 `content` (= 読んだ票) が変わるたびに、
 * 張り付いている間だけ最下端へ送る。 Markdown の描き終わりなど、 遅れて中身が伸びる分は容器の子の大きさの変化で拾う。
 */
export function useFollowLatest(ticketId, content) {
  const scrollerRef = useRef(null)
  const stuckRef = useRef(true)
  const lastTopRef = useRef(0)
  const followedIdRef = useRef(null)

  const follow = useCallback(() => {
    const el = scrollerRef.current
    if (!el) return
    jumpToBottom(el)
    lastTopRef.current = el.scrollTop
  }, [])

  // 描く前に最下端へ送る (= 上から開いて一瞬見えるのを防ぐ)
  useLayoutEffect(() => {
    if (followedIdRef.current !== ticketId) {
      followedIdRef.current = ticketId
      stuckRef.current = true
    }
    if (stuckRef.current) follow()
  }, [ticketId, content, follow])

  // 容器と、 その子 (= 頭・原文・件の並び) の大きさが変わったら、 張り付いている間は最下端へ送り直す。
  // 子の増減 (= 件の並びが読み込み後に出る) は MutationObserver で拾い、 見る子を貼り直す。
  useEffect(() => {
    const el = scrollerRef.current
    if (!el || typeof ResizeObserver === 'undefined') return undefined
    const resizeObserver = new ResizeObserver(() => { if (stuckRef.current) follow() })
    const observeChildren = () => {
      resizeObserver.disconnect()
      resizeObserver.observe(el)
      for (const child of el.children) resizeObserver.observe(child)
    }
    observeChildren()
    const mutationObserver = typeof MutationObserver === 'undefined' ? null : new MutationObserver(observeChildren)
    mutationObserver?.observe(el, { childList: true })
    return () => { resizeObserver.disconnect(); mutationObserver?.disconnect() }
  }, [follow])

  const onScroll = useCallback(() => {
    const el = scrollerRef.current
    if (!el) return
    stuckRef.current = nextStuck({
      stuck: stuckRef.current,
      prevTop: lastTopRef.current,
      top: el.scrollTop,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    })
    lastTopRef.current = el.scrollTop
  }, [])

  return { scrollerRef, onScroll }
}
