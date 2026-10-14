// 入力欄の 🎙: 押して話し、 もう 1 度押すと、 聞き取った文をこのタブへ送る。 声を聞き取る agent のタブにだけ出る。
// 録っている間は赤い地で脈打ち (= 押すと送る)、 聞き取りを待つ間は押せない。 失敗の理由は上部の 🔊 の下に出る。
// 録っている間も 🎙 のまま (= 隣の停止ボタン ■ と見分けられるように、 形ではなく色と動きで見せる)。

import { useEffect, useSyncExternalStore } from 'react'
import { subscribe, getSnapshot } from '../../state/voice.js'
import { useT } from '../../i18n/t.js'
import { pressMic, cancelListening } from './voice.js'
import './MicButton.css'

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
  return (
    <button
      type="button"
      className={`mic${phase ? ` ${phase}` : ''}`}
      onClick={() => pressMic(sid, onSend)}
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
