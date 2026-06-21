import { useState, useRef, useEffect, useLayoutEffect, useCallback } from 'react'

// 「最新が見えてる」 と判定するボトム余白 (= px)。 数 px の指の振動を許容する目的で 30px。
// ユーザがメッセージを戻し読みする時は最低でも 1 段スクロール (= 数十 px) するので識別可能。
const AT_BOTTOM_THRESHOLD_PX = 30
// scrollToBottom 実行後、 自前 scroll を「ユーザ操作」 と誤検知させないための猶予時間。
// この間の onScroll は無視する。 短いと render 遅延中の onScroll を拾い、 長いと
// ユーザ反応に対する反映が遅れる。
const PROGRAMMATIC_SCROLL_GUARD_MS = 200

// 通常 column (古い→新しい が DOM 上→下) で、 JS で底辺へ scroll する古典構成。
//
// 旧実装は flex-direction: column-reverse のトリックを使っていたが、 iOS Safari WebKit で
// column-reverse + overflow:auto の scrollTop 解釈が壊れていて (= 視覚順序は反転、 数値は
// 通常 column 仕様) 、 「↓ボタンが下端で出る」「details が上に展開」「scroll 末尾追従が
// 異常に強い」 等の連鎖症状を起こしていた (= 2026-05-19 修正、 WebKit #225278 系列の bug
// と整合)。 通常 column に戻すことで全て解消する。
//
//   - isAtBottom = (scrollHeight - scrollTop - clientHeight ≤ 30)、 = 「最新が見えてる」
//   - scrollToBottom = scrollTop を scrollHeight 相当に上げる
//   - 上スクロール (scrollTop が小さくなる) = 古いメッセージ閲覧
//   - 新着メッセージ追従は isAtBottom 中のみ JS で再 scroll、 そうでなければ hasNew=true
//
// 起動 / タブ切替時は useLayoutEffect で paint 前に底へ flush (= 前 session の scroll 残留防止)。
//
// 遅延 layout 追従戦略 (= F-09 改修、 2026-06-21):
//   旧: setTimeout を [50,150,400,1000,2500] ms の 5 段で打って毎回再 scroll。 同期 1 回 +
//       rAF retry + ResizeObserver で「実 layout 確定タイミング」 を捉える方が正確かつ
//       無駄が少ない。 5 段 timeout は paint 結果に関わらず時間で叩くので、 ユーザが間に
//       上スクロールしたら isAtBottomRef=false で no-op になるが、 timeout 自体は走り続け
//       無駄な setTimeout を抱えていた。
//   新: 同期で 1 回 + rAF で 1 回 + ResizeObserver が以後の layout 拡大を全て拾う。 RO の
//       observe は scroll container 自身 (= 子要素は冗長で、 children が増えるたび observe
//       する fan-out も不要、 親 1 つで子の拡大は全部拾える)。 ResizeObserver は実 layout
//       変化時にしか発火しないので、 無関係な setTimeout は廃止。
export function useAutoScroll({ messages, activeSession, viewMode }) {
  const [showScrollBtn, setShowScrollBtn] = useState(false)
  const [hasNew, setHasNew] = useState(false)
  const isAtBottomRef = useRef(true)
  const scrollerDomRef = useRef(null)
  const msgLengthRef = useRef({})
  const programmaticScrollRef = useRef(false)
  const scrollEndTimerRef = useRef(null)
  const sid = activeSession?.id

  // 同期: 最下端 (= 最新が見える状態) に移動
  const scrollToBottomSync = useCallback(() => {
    const el = scrollerDomRef.current
    if (!el) return
    isAtBottomRef.current = true
    el.scrollTop = el.scrollHeight
  }, [])

  // sid 切替 / 初期マウント後の遅延 layout 追従用。 ユーザが既に上スクロールしてれば
  // (= isAtBottomRef=false) 何もしない、 末尾追従中だけ底辺へ寄せ直す。
  const scrollToBottomIfFollowing = useCallback(() => {
    const el = scrollerDomRef.current
    if (!el || !isAtBottomRef.current) return
    el.scrollTop = el.scrollHeight
  }, [])

  // 公開: 「↓ 最新へ」 ボタン or send 直後に呼ぶ用。
  // 同期 1 回 + rAF 1 回。 以後の遅延 layout (= Markdown / code highlight / 画像 /
  // details 展開) は ResizeObserver effect 側の observer が拾って自動追従する
  // (= F-09 統合)。 isAtBottomRef は guard 中 true 維持。
  const scrollToBottom = useCallback(() => {
    const el = scrollerDomRef.current
    if (!el) return
    programmaticScrollRef.current = true
    isAtBottomRef.current = true
    setHasNew(false)
    el.scrollTop = el.scrollHeight
    clearTimeout(scrollEndTimerRef.current)
    scrollEndTimerRef.current = setTimeout(() => {
      programmaticScrollRef.current = false
    }, PROGRAMMATIC_SCROLL_GUARD_MS)
    // 直後の paint 後にもう 1 回 (= 同 tick で scrollHeight が確定しないケース吸収)
    requestAnimationFrame(() => {
      const e = scrollerDomRef.current
      if (e && isAtBottomRef.current) e.scrollTop = e.scrollHeight
    })
  }, [])

  // 起動 / タブ切替: paint 前に底へ flush (= 前 session の scroll 残留防止)。
  // 同期 + rAF 1 回。 以後の長い遅延 layout は ResizeObserver effect が拾う。
  useLayoutEffect(() => {
    if (!sid) return
    // ターミナル画面では DOM が xterm 側、 messages container は表示外なので scroll しない。
    // 同じ effect を chat / terminal 切替ごとに走らせて、 terminal → chat に戻った時にも
    // 最新位置へ寄せ直す (= 「ターミナルに移って戻ったら最新に行かない」 症状の解消)。
    if (viewMode && viewMode !== 'chat') return
    isAtBottomRef.current = true
    setShowScrollBtn(false)
    setHasNew(false)
    msgLengthRef.current[sid] = (messages[sid] || []).length
    scrollToBottomSync()
    const rafId = requestAnimationFrame(scrollToBottomIfFollowing)
    return () => cancelAnimationFrame(rafId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sid, viewMode])

  // 新着メッセージ:
  //   isAtBottom 中なら底に追従、 上スクロール中 (= 古いメッセージ閲覧) なら hasNew=true で赤丸表示。
  //   通常 column では新着で要素が下に伸びるだけ、 scroll 位置は変わらないので明示追従が必要。
  useEffect(() => {
    if (!sid) return
    const cur = messages[sid] || []
    const currentLen = cur.length
    const prevLen = msgLengthRef.current[sid] || 0
    msgLengthRef.current[sid] = currentLen

    if (currentLen > prevLen) {
      if (isAtBottomRef.current) {
        scrollToBottomSync()
      } else {
        setHasNew(true)
      }
    }
  }, [messages, sid, scrollToBottomSync])

  // 画面回転 / キーボード表示等のレイアウト変化時は最新位置に戻す (isAtBottom 中のみ)
  useEffect(() => {
    const onResize = () => {
      if (isAtBottomRef.current) scrollToBottomSync()
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [scrollToBottomSync])

  // scroll 容器の子要素 layout が遅延確定する (= Markdown / コードブロック / 画像 / details
  // 展開等) ケースに追従するための ResizeObserver。 isAtBottom 中なら scrollHeight が伸びる
  // たびに底辺へ送り直す。 旧実装は children を 1 つずつ observe + MutationObserver で
  // 新規 child を追加 observe していたが、 親 container 1 つを observe するだけで子の
  // 拡大は scrollHeight 変化として拾える (= F-09 / F-10 整理、 fan-out 廃止)。
  useEffect(() => {
    const el = scrollerDomRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    let lastHeight = -1
    const ro = new ResizeObserver(() => {
      // 実値が変化した時だけ反応 (= F-10、 RO 二重発火連鎖を抑える)。
      const h = el.scrollHeight
      if (h === lastHeight) return
      lastHeight = h
      if (isAtBottomRef.current) scrollToBottomSync()
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [scrollToBottomSync, sid])

  const onScroll = useCallback(() => {
    if (programmaticScrollRef.current) return
    const el = scrollerDomRef.current
    if (!el) return
    // 通常 column: 底辺 = scrollTop が scrollHeight - clientHeight に近い
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    const atBottom = distanceFromBottom <= AT_BOTTOM_THRESHOLD_PX
    isAtBottomRef.current = atBottom
    if (atBottom) setHasNew(false)
    // 同値時は React が re-render を bailout するので、 毎回 set で OK。
    setShowScrollBtn(!atBottom)
  }, [])

  return {
    scrollerDomRef,
    isAtBottomRef,
    showScrollBtn,
    hasNew,
    scrollToBottom,
    onScroll,
  }
}
