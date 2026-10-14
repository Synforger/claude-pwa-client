// 入力欄の声のボタン 2 つ。 声を持つ agent のタブにだけ出る。
//
//   🔊 / 🔇 (= 外側): agent の返事を声で鳴らすか。 オンの間に送った文には、 声で聞いている印が付く。 オフにすると、
//                    マイクも閉じて普段の文字のチャットに戻る
//   🎙 (= 内側):      マイクの消音と解除。 声がオンで、 その agent が声を聞き取る時だけ出る。 解除の間は話すだけで
//                    送られ、 消音の間は打って送り、 返事だけを声で聞く。 消音を選ぶと、 次に声をオンにした時も消音で始まる
//
// 色と動きで今を見せる: 🔊 は鳴らせる (= 青の枠) / 鳴っている (= 青の枠が脈打つ)。 🎙 は聞いている (= 緑の枠) /
// 人が話している (= 枠が脈打つ) / 言い終えを見ている・文字にしている (= 薄い点滅) / 消音 (= 斜線)。
// 失敗の理由はボタンの上に出る。

import { useEffect, useSyncExternalStore } from 'react'
import { subscribe, getSnapshot } from '../../state/voice.js'
import { useT } from '../../i18n/t.js'
import { toggleVoice, toggleMic, closeConversation, refreshVoiceAvailable } from './voice.js'
import './VoiceButtons.css'

export default function VoiceButtons({ sid, onSend }) {
  const voice = useSyncExternalStore(subscribe, getSnapshot)
  const t = useT()

  useEffect(() => { if (sid) refreshVoiceAvailable(sid) }, [sid])
  // タブを移ったら、 そのタブの声とマイクを閉じる (= 送る関数は、 今見ているタブへ送る)。
  useEffect(() => () => { if (sid && getSnapshot().on[sid]) closeConversation(sid) }, [sid])

  if (!sid || !voice.available[sid]) return null
  const on = !!voice.on[sid]
  const voiceState = !on ? 'off' : voice.speaking[sid] ? 'replying' : 'on'
  // マイクが開いているかは、 会話の今 (= phase) が在るかで決まる
  const micState = voice.phase[sid] || 'muted'
  const error = voice.error[sid] || ''
  return (
    <span className="voice-buttons">
      {on && voice.listen[sid] && (
        <button
          type="button"
          className={`voice-mic ${micState}`}
          onClick={() => toggleMic(sid, onSend)}
          aria-pressed={micState !== 'muted'}
          aria-label={t('chat.mic_label')}
          title={t(`chat.mic_${micState}`)}
          data-testid="chat-mic-button"
          data-state={micState}
        >
          🎙
        </button>
      )}
      <button
        type="button"
        className={`voice-toggle ${voiceState}${error ? ' failed' : ''}`}
        onClick={() => toggleVoice(sid, onSend)}
        aria-pressed={on}
        aria-label={t('chat.voice_label')}
        title={t(`chat.voice_${voiceState}`)}
        data-testid="chat-voice-button"
        data-state={voiceState}
      >
        {on ? '🔊' : '🔇'}
      </button>
      {error && <span className="voice-error" role="alert" data-testid="voice-error">{error}</span>}
    </span>
  )
}
