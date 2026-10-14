// 入力欄の 🎙: 押している間だけ録り、 離すと、 聞き取った文をこのタブへ送る。 声を聞き取る agent のタブにだけ出る。
// 録っている間は赤い地で脈打ち、 聞き取りを待つ間は押せない。 失敗の理由は上部の 🔊 の下に出る。
// 録っている間も 🎙 のまま (= 隣の停止ボタン ■ と見分けられるように、 形ではなく色と動きで見せる)。
//
// 指やマウスがボタンの外へずれても、 離した時が終わり (= pointer capture)。 キーボードは Space / Enter を押している間。

import { useEffect, useSyncExternalStore } from 'react'
import { subscribe, getSnapshot } from '../../state/voice.js'
import { useT } from '../../i18n/t.js'
import { startListening, finishListening, cancelListening } from './voice.js'
import './MicButton.css'

const HOLD_KEYS = new Set([' ', 'Enter'])

export default function MicButton({ sid, onSend }) {
  const voice = useSyncExternalStore(subscribe, getSnapshot)
  const t = useT()

  // タブを移ったら、 そのタブの録音を手放す (= 送る関数は、 今見ているタブへ送る)。
  useEffect(() => () => {
    if (sid && getSnapshot().listening[sid]) cancelListening(sid)
  }, [sid])

  if (!sid || !voice.available[sid] || !voice.listen[sid]) return null
  const phase = voice.listening[sid] || ''
  const title = phase === 'recording' ? t('chat.mic_stop') : phase === 'hearing' ? t('chat.mic_hearing') : t('chat.mic_start')
  const start = () => startListening(sid)
  const finish = () => finishListening(sid, onSend)
  return (
    <button
      type="button"
      className={`mic${phase ? ` ${phase}` : ''}`}
      onPointerDown={(e) => {
        if (e.button !== 0) return
        e.preventDefault()
        try { e.currentTarget.setPointerCapture(e.pointerId) } catch { /* 捕まえられない環境でも離した所で終わる */ }
        start()
      }}
      onPointerUp={finish}
      onPointerCancel={finish}
      onKeyDown={(e) => { if (HOLD_KEYS.has(e.key) && !e.repeat) { e.preventDefault(); start() } }}
      onKeyUp={(e) => { if (HOLD_KEYS.has(e.key)) { e.preventDefault(); finish() } }}
      onContextMenu={(e) => e.preventDefault()}
      disabled={phase === 'hearing'}
      aria-pressed={phase === 'recording'}
      aria-label={t('chat.mic_label')}
      title={title}
      data-testid="chat-mic-button"
      data-phase={phase || 'idle'}
    >
      {phase === 'hearing' ? '…' : '🎙'}
    </button>
  )
}
