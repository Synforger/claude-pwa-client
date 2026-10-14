// 入力欄の声のボタン 3 つ。 声を持つ agent のタブにだけ出る。
//
//   🔊 / 🔇 (= 外側): agent の返事を声で鳴らすか。 オンの間に送った文には、 声で聞いている印が付く。 オフにすると、
//                    マイクも閉じて普段の文字のチャットに戻る
//   🎙 (= 内側):      マイクを開く / 閉じる。 声がオンで、 その agent が声を聞き取る時だけ出る。 開いている間は話す
//                    だけで送られ、 閉じている間は打って送り、 返事だけを声で聞く。 声をオンにしただけではマイクを
//                    取らず、 🎙 を開いたまま声を切ったタブだけ、 次に声をオンにした時もマイクを開く
//   🗣 (= 🎙 と 🔊 の間): 会話の間、 agent の返事を声にするか。 切にすると声だけが止まり、 マイクと文字 (= iPhone の app
//                    の小窓も) はそのまま。 会話の間だけ出る
//
// 🔊 にできるのは 1 つのタブだけで、 別のタブを見ている間も、 そのタブの会話は続く (= 返事を鳴らし、 話した文は
// そのタブへ送る)。 別のタブで 🔊 にすると、 前のタブの会話は閉じる。
//
// 色と動きで今を見せる: 🔊 は鳴らせる (= 青の枠) / 鳴っている (= 青の枠が脈打つ)。 🎙 は聞いている (= 緑の枠) /
// 人が話している (= 枠が脈打つ) / 言い終えを見ている・文字にしている (= 薄い点滅) / 閉じている (= 斜線)。
// 失敗の理由はボタンの上に出る。

import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { subscribe, getSnapshot } from '../../state/voice.js'
import { useT } from '../../i18n/t.js'
import { subscribe as onVolume, getSnapshot as volumeOf, VOLUME_MAX } from '../../state/voiceVolume.js'
import { toggleVoice, toggleMic, toggleSpeech, refreshVoiceAvailable, changeVolume } from './voice.js'
import './VoiceButtons.css'

// 🔊 をこの長さ押し続けると、 声の大きさのつまみが出る (= iOS の長押しのメニューより先に出す)
const LONG_PRESS_MS = 450
// つまみを閉じるために 🔊 を押した時、 その押下の click とみなす間 (= 押してから click が届くまでの時間の上限)
const CLOSING_CLICK_MS = 1000

export default function VoiceButtons({ sid }) {
  const voice = useSyncExternalStore(subscribe, getSnapshot)
  const { volume } = useSyncExternalStore(onVolume, volumeOf)
  const t = useT()
  const [sliderOpen, setSliderOpen] = useState(false)
  // 長押しで開いた時は、 指を離した時の click で声を切り替えない
  const press = useRef({ timer: null, long: false, closedAt: 0 })
  // つまみは、 つまみの外を押しても閉じる。 🔊 を押して閉じた時は、 その押下で声を切り替えない
  const sliderRef = useRef(null)
  const toggleRef = useRef(null)
  useEffect(() => {
    if (!sliderOpen) return undefined
    const closeOutside = (e) => {
      if (sliderRef.current?.contains(e.target)) return
      if (toggleRef.current?.contains(e.target)) press.current.closedAt = Date.now()
      setSliderOpen(false)
    }
    document.addEventListener('pointerdown', closeOutside, true)
    return () => document.removeEventListener('pointerdown', closeOutside, true)
  }, [sliderOpen])
  const startPress = () => {
    press.current.long = false
    clearTimeout(press.current.timer)
    press.current.timer = setTimeout(() => { press.current.long = true; setSliderOpen(true) }, LONG_PRESS_MS)
  }
  const endPress = () => clearTimeout(press.current.timer)

  useEffect(() => { if (sid) refreshVoiceAvailable(sid) }, [sid])

  if (!sid || !voice.available[sid]) return null
  const on = !!voice.on[sid]
  const voiceState = !on ? 'off' : voice.speaking[sid] ? 'replying' : 'on'
  // マイクが開いているかは、 会話の今 (= phase) が在るかで決まる
  const micState = voice.phase[sid] || 'muted'
  const error = voice.error[sid] || ''
  const speechState = voice.quiet[sid] ? 'quiet' : 'speaking'
  return (
    <span className="voice-buttons">
      {on && voice.listen[sid] && (
        <button
          type="button"
          className={`voice-mic ${micState}`}
          onClick={() => toggleMic(sid)}
          aria-pressed={micState !== 'muted'}
          aria-label={t('chat.mic_label')}
          title={t(`chat.mic_${micState}`)}
          data-testid="chat-mic-button"
          data-state={micState}
        >
          🎙
        </button>
      )}
      {on && (
        <button
          type="button"
          className={`voice-speech ${speechState}`}
          onClick={() => toggleSpeech(sid)}
          aria-pressed={speechState === 'speaking'}
          aria-label={t('chat.speech_label')}
          title={t(`chat.speech_${speechState}`)}
          data-testid="chat-speech-button"
          data-state={speechState}
        >
          🗣
        </button>
      )}
      <button
        type="button"
        className={`voice-toggle ${voiceState}${error ? ' failed' : ''}`}
        ref={toggleRef}
        onClick={() => {
          const closing = Date.now() - press.current.closedAt < CLOSING_CLICK_MS
          press.current.closedAt = 0
          if (press.current.long || closing) { press.current.long = false; return }
          toggleVoice(sid)
        }}
        onPointerDown={startPress}
        onPointerUp={endPress}
        onPointerLeave={endPress}
        onPointerCancel={endPress}
        onContextMenu={(e) => e.preventDefault()}
        aria-pressed={on}
        aria-label={t('chat.voice_label')}
        title={t(`chat.voice_${voiceState}`)}
        data-testid="chat-voice-button"
        data-state={voiceState}
      >
        {on ? '🔊' : '🔇'}
      </button>
      {sliderOpen && (
        <span className="voice-volume" data-testid="voice-volume" ref={sliderRef}>
          <input
            type="range"
            min={0}
            max={VOLUME_MAX * 100}
            step={5}
            value={Math.round(volume * 100)}
            onChange={(e) => changeVolume(sid, Number(e.target.value) / 100)}
            aria-label={t('chat.voice_volume')}
          />
          <span className="voice-volume-value">{Math.round(volume * 100)}%</span>
          <button type="button" onClick={() => setSliderOpen(false)} aria-label={t('chat.voice_volume_close')}>✕</button>
        </span>
      )}
      {error && <span className="voice-error" role="alert" data-testid="voice-error">{error}</span>}
    </span>
  )
}
