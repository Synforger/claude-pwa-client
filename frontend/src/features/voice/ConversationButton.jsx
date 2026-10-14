// 入力欄の会話のボタン: 押すと会話を開き、 もう 1 度押すと閉じる。 声を持つ agent のタブにだけ出る。
//
// 開いている間は、 話すだけで送られ (= 言い終えたら、 聞き取った文がこのタブへ送られる)、 返事は声で返る。
// 閉じている間は、 マイクを閉じ、 返事も鳴らさない (= 普段の文字のチャット)。 声を聞き取らない agent のタブでは、
// 返事を声で鳴らすかだけを切り替える。
//
// 色と動きで今を見せる: 聞いている (= 緑の枠) / 人が話している (= 枠が脈打つ) / 言い終えを見ている・文字にしている
// (= 薄い点滅) / 返事が鳴っている (= 聞くのを止めている)。 失敗の理由はボタンの上に出る。

import { useEffect, useSyncExternalStore } from 'react'
import { subscribe, getSnapshot } from '../../state/voice.js'
import { useT } from '../../i18n/t.js'
import { toggleConversation, closeConversation, refreshVoiceAvailable } from './voice.js'
import './ConversationButton.css'

export default function ConversationButton({ sid, onSend }) {
  const voice = useSyncExternalStore(subscribe, getSnapshot)
  const t = useT()

  useEffect(() => { if (sid) refreshVoiceAvailable(sid) }, [sid])
  // タブを移ったら、 そのタブの会話を閉じる (= 送る関数は、 今見ているタブへ送る)。
  useEffect(() => () => { if (sid && getSnapshot().on[sid]) closeConversation(sid) }, [sid])

  if (!sid || !voice.available[sid]) return null
  const on = !!voice.on[sid]
  const listens = !!voice.listen[sid]
  const state = !on ? 'off' : voice.speaking[sid] ? 'replying' : (voice.phase[sid] || (listens ? 'starting' : 'replying'))
  const error = voice.error[sid] || ''
  return (
    <span className="conversation-wrap">
      <button
        type="button"
        className={`conversation ${state}${error ? ' failed' : ''}`}
        onClick={() => toggleConversation(sid, onSend)}
        aria-pressed={on}
        aria-label={t(listens ? 'chat.conversation_label' : 'chat.voice_label')}
        title={t(`chat.conversation_${state}`)}
        data-testid="chat-conversation-button"
        data-state={state}
      >
        {listens ? '🎙' : on ? '🔊' : '🔇'}
      </button>
      {error && <span className="conversation-error" role="alert" data-testid="voice-error">{error}</span>}
    </span>
  )
}
