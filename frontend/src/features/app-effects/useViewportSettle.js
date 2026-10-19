import { useEffect } from 'react'
import { httpClient } from '../../transport/http.ts'

// 画面が上へずれたまま残る件の戻し (= iPhone のホーム画面の PWA と iPhone の app の両方)。
//
// 画面の根は 100dvh で、 body は overflow: hidden なので、 文書が縦に送られる (= scrollY が 0 でない) 理由は、
// iOS がキーボードを出す時に入力欄を見せるため文書ごと上へ送った分しか無い。 閉じた時にその送りが戻らないことがあり、
// 画面の全部が上へずれたまま残る。 キーボードが閉じ切った時 (= visualViewport の大きさが変わった時) と、 裏から
// 戻った時に、 入力欄に focus が無いのに送りが残っていれば 0 へ戻す。
//
// 戻した時は、 その時の値を backend の記録へ 1 行残す (= logs/backend.error.log の `sw-log` の `viewport:settle`)。
// ずれが残ったのにこの行が無ければ、 原因はこの送りではない。

const EDITABLE = 'input, textarea, select, [contenteditable=""], [contenteditable="true"]'

function editing() {
  const el = document.activeElement
  return !!el && el !== document.body && !!el.matches?.(EDITABLE)
}

function report(payload) {
  httpClient.apiFetch('/log/sw', { method: 'POST', jsonBody: payload }).catch(() => {})
}

// trigger = 何が確かめさせたか (= `viewport` / `visible`)。 戻したら true。
export function settleViewport(trigger, send = report) {
  if (editing()) return false
  const scrollY = window.scrollY || document.documentElement.scrollTop || 0
  if (scrollY === 0) return false
  const vv = window.visualViewport
  send({
    stage: 'viewport:settle',
    trigger,
    scrollY,
    vvTop: vv ? vv.offsetTop : null,
    vvHeight: vv ? vv.height : null,
    innerHeight: window.innerHeight,
  })
  window.scrollTo(0, 0)
  return true
}

export function useViewportSettle() {
  useEffect(() => {
    const vv = window.visualViewport
    const onViewport = () => settleViewport('viewport')
    const onVisible = () => {
      if (document.visibilityState === 'visible') settleViewport('visible')
    }
    vv?.addEventListener('resize', onViewport)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      vv?.removeEventListener('resize', onViewport)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [])
}
