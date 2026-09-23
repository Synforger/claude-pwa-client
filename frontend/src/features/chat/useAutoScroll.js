import { useRef, useEffect, useLayoutEffect, useCallback, useSyncExternalStore } from 'react'
import {
  subscribe as subscribeUi,
  getSnapshot as getUiSnapshot,
  setScroll,
} from '../../state/ui.js'
import { nextStuck } from './stickToBottom.js'
import { SETTLE_CHECK_MS, reportScroll } from './scrollProbe.js'

// 最下端へ一瞬で飛ぶ。 `.messages` は CSS で scroll-behavior: smooth なので、 scrollTop への代入は
// アニメーションになる。 アニメーションの目標は開始時点の最下端に固定され、 途中で中身が伸びると
// 手前で止まり、 送り直すと iOS Safari は途中で打ち切ったり少し戻ったりする (= 2026-09-23 の実機
// 記録で iPhone だけ 100-1,500px 手前に止まっていた)。 自前の追従は behavior: 'instant' で飛ぶ
// (= 指のスクロールには影響しない)。
function jumpToBottom(el) {
  if (typeof el.scrollTo === 'function') {
    el.scrollTo({ top: el.scrollHeight, behavior: 'instant' })
  } else {
    el.scrollTop = el.scrollHeight
  }
}

// 通常 column (古い→新しい が DOM 上→下) で、 JS で底辺へ scroll する古典構成。
//
// 旧実装は flex-direction: column-reverse のトリックを使っていたが、 iOS Safari WebKit で
// column-reverse + overflow:auto の scrollTop 解釈が壊れていて (= 視覚順序は反転、 数値は
// 通常 column 仕様) 、 「↓ボタンが下端で出る」「details が上に展開」「scroll 末尾追従が
// 異常に強い」 等の連鎖症状を起こしていた (= 2026-05-19 修正、 WebKit #225278 系列の bug
// と整合)。 通常 column に戻すことで全て解消する。
//
//   - isAtBottom = 最下端に張り付いている (= 中身が伸びたら最下端へ送り続ける)。 外れるのは
//     ユーザが上へスクロールした時だけで、 最下端からの距離では外さない (= stickToBottom.js)。
//     2026-09-23 まで距離 (> 30px) で外していたため、 送った直後に中身が伸びると「離れた」 と
//     誤判定して追従が止まり、 開いた時や ↓ ボタンで途中に止まっていた
//   - scrollToBottom = scrollTop を scrollHeight 相当に上げる
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
//   新: 同期で 1 回 + rAF で 1 回 + ResizeObserver が以後の layout 拡大を拾う。 RO は
//       容器の子要素を observe する (= 固定高さの容器自身は子が伸びても box 不変で発火
//       しないため、 子を見る必要がある。 詳細は下の RO effect コメント)。 ResizeObserver は
//       実 layout 変化時にしか発火しないので、 無関係な setTimeout は廃止。
export function useAutoScroll({ messages, activeSession, viewMode }) {
  // Phase J-12 (= 2026-06-29): showScrollBtn / hasNew を state/ui.js.scroll singleton に統合
  // (= 旧 useState、 audit B sweep)。 wrapper setShowScrollBtn / setHasNew は単一 field の
  // setScroll patch dispatch、 既存呼出を無修正で通す。 isAtBottomRef は instance-local の
  // 同期 ref なので store には載せない (= scroll callback の同期判定で必要)。
  const uiSnap = useSyncExternalStore(subscribeUi, getUiSnapshot)
  const showScrollBtn = uiSnap.scroll.showScrollBtn
  const hasNew = uiSnap.scroll.hasNew
  const setShowScrollBtn = useCallback((v) => {
    if (getUiSnapshot().scroll.showScrollBtn !== v) setScroll({ showScrollBtn: v })
  }, [])
  const setHasNew = useCallback((v) => {
    if (getUiSnapshot().scroll.hasNew !== v) setScroll({ hasNew: v })
  }, [])
  const isAtBottomRef = useRef(true)
  const scrollerDomRef = useRef(null)
  const msgLengthRef = useRef({})
  const lastTopRef = useRef(0)
  const settleTimerRef = useRef(null)
  const sid = activeSession?.id

  // 同期: 最下端 (= 最新が見える状態) に移動
  const scrollToBottomSync = useCallback(() => {
    const el = scrollerDomRef.current
    if (!el) return
    isAtBottomRef.current = true
    jumpToBottom(el)
    lastTopRef.current = el.scrollTop
  }, [])

  // 公開: 「↓ 最新へ」 ボタン or send 直後に呼ぶ用。
  // 同期 1 回 + rAF 1 回。 以後の遅延 layout (= Markdown / code highlight / 画像 /
  // details 展開) は ResizeObserver effect 側の observer が拾って自動追従する
  // (= F-09 統合)。 isAtBottomRef は guard 中 true 維持。
  // 自前の scroll は常に下向き (= scrollTop を増やす) なので、 張り付き判定を誤らせない
  // (= 旧実装の「自前 scroll 直後 200ms は onScroll を無視する」 猶予は不要になった)。
  const scrollToBottom = useCallback((reason = 'button') => {
    const el = scrollerDomRef.current
    if (!el) return
    isAtBottomRef.current = true
    setHasNew(false)
    setShowScrollBtn(false)
    jumpToBottom(el)
    lastTopRef.current = el.scrollTop
    // 直後の paint 後にもう 1 回 (= 同 tick で scrollHeight が確定しないケース吸収)
    requestAnimationFrame(() => {
      const e = scrollerDomRef.current
      if (e && isAtBottomRef.current) {
        jumpToBottom(e)
        lastTopRef.current = e.scrollTop
      }
    })
    // 【一時計測】 遅れた伸びが収まった頃に、 本当に最下端に居るかを記録する。
    clearTimeout(settleTimerRef.current)
    settleTimerRef.current = setTimeout(() => {
      const e = scrollerDomRef.current
      if (e) reportScroll('settle', e, { reason, stuck: isAtBottomRef.current })
    }, SETTLE_CHECK_MS)
  }, [setHasNew, setShowScrollBtn])

  // 起動 / タブ切替: paint 前に底へ flush (= 前 session の scroll 残留防止)。
  // scrollToBottom 経由 (= 自前 rAF retry + 【一時計測】 の settle 記録) で行う。
  // 遅延展開で距離が開いても張り付きは外れない (= stickToBottom.js) ので、 以後は
  // ResizeObserver が最下端へ送り続ける。
  useLayoutEffect(() => {
    if (!sid) return
    // ターミナル画面では DOM が xterm 側、 messages container は表示外なので scroll しない。
    // 同じ effect を chat / terminal 切替ごとに走らせて、 terminal → chat に戻った時にも
    // 最新位置へ寄せ直す (= 「ターミナルに移って戻ったら最新に行かない」 症状の解消)。
    if (viewMode && viewMode !== 'chat') return
    setShowScrollBtn(false)
    setHasNew(false)
    msgLengthRef.current[sid] = (messages[sid] || []).length
    scrollToBottom('open')
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
  }, [messages, sid, scrollToBottomSync, setHasNew])

  // 画面回転 / キーボード表示等のレイアウト変化時は最新位置に戻す (isAtBottom 中のみ)
  useEffect(() => {
    const onResize = () => {
      if (isAtBottomRef.current) scrollToBottomSync()
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [scrollToBottomSync])

  // 前面復帰時に最下端へ寄せ直す (= 「繋ぎ直したら最新の最下部に行かない」 の解消)。
  // iOS PWA は bg 中に socket を suspend し、 復帰で reconnect → replay で新着が届くが、
  // bg 中の layout 変化 (= keyboard / safe-area / 回転) が onScroll を発火させて
  // isAtBottomRef を false に倒すと、 復帰後の replay 追従が効かず最新に貼り付かない。
  // hidden 時点で最下端に居たら復帰時に scrollToBottom を再宣言し (= isAtBottomRef=true に
  // 戻す)、 以後届く replay も追従を回復させる。 上スクロールで戻し読み中に bg → 復帰した
  // 場合は wasAtBottom=false なので勝手に飛ばさない。
  useEffect(() => {
    let wasAtBottom = true
    const onVis = () => {
      if (document.visibilityState === 'hidden') {
        wasAtBottom = isAtBottomRef.current
      } else if (document.visibilityState === 'visible') {
        if (wasAtBottom && (!viewMode || viewMode === 'chat')) scrollToBottom('visible')
      }
    }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [scrollToBottom, viewMode])

  // scroll 容器の子要素 layout が遅延確定する (= Markdown / コードブロック / 画像 / details
  // 展開等) ケースに追従するための ResizeObserver。 isAtBottom 中なら scrollHeight が伸びる
  // たびに底辺へ送り直す。
  //
  // 重要: ResizeObserver は observe した要素**自身の box サイズ**変化しか発火しない。 scroll
  // 容器 (= .messages) は固定高さの viewport なので、 子 (= メッセージ) が伸びて scrollHeight が
  // 増えても容器自身の box は変わらず **発火しない**。 「親 1 つ observe で子の拡大も拾える」 は
  // 誤りで、 画像ロード / code highlight / markdown 展開の遅延で高さが伸びる分を追従できず、
  // 「↓ 最新へ」 ボタンが最下端まで行かず途中で止まる原因だった。 → 子要素を observe し、
  // 子の増減は MutationObserver で拾って observe を貼り直す (= 実質 scrollHeight 変化を捕捉)。
  useEffect(() => {
    const el = scrollerDomRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    let lastHeight = -1
    const ro = new ResizeObserver(() => {
      // 実値が変化した時だけ反応 (= RO 二重発火連鎖を抑える)。 scrollHeight は容器から読む。
      const h = el.scrollHeight
      if (h === lastHeight) return
      lastHeight = h
      if (isAtBottomRef.current) scrollToBottomSync()
    })
    // 容器自身 (= viewport resize / 回転) + 全子要素 (= 中身の高さ変化) を observe。
    const reobserve = () => {
      ro.disconnect()
      ro.observe(el)
      for (const child of el.children) ro.observe(child)
    }
    reobserve()
    // 子の増減 (= 新着メッセージ / session 切替) で observe を貼り直す。
    const mo = typeof MutationObserver !== 'undefined' ? new MutationObserver(reobserve) : null
    mo?.observe(el, { childList: true })
    return () => { ro.disconnect(); mo?.disconnect() }
  }, [scrollToBottomSync, sid])

  const onScroll = useCallback(() => {
    const el = scrollerDomRef.current
    if (!el) return
    const top = el.scrollTop
    const stuck = nextStuck({
      stuck: isAtBottomRef.current,
      prevTop: lastTopRef.current,
      top,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    })
    // 【一時計測】 張り付きが外れた瞬間 (= 本来はユーザの上スクロールだけ) を記録する。
    if (isAtBottomRef.current && !stuck) reportScroll('escape', el, { prevTop: Math.round(lastTopRef.current) })
    lastTopRef.current = top
    isAtBottomRef.current = stuck
    if (stuck) setHasNew(false)
    // ↓ ボタンは張り付きが外れている時だけ出す (= 中身が伸びて一瞬距離が開いても出さない)。
    // 同値時は React が re-render を bailout するので、 毎回 set で OK。
    setShowScrollBtn(!stuck)
  }, [setHasNew, setShowScrollBtn])

  return {
    scrollerDomRef,
    isAtBottomRef,
    showScrollBtn,
    hasNew,
    scrollToBottom,
    onScroll,
  }
}
