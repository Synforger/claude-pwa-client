// 入力欄の声のボタン 2 つ。 声を持つ agent のタブにだけ出る。 2 つは別々に入 / 切でき、 どちらかが入っている間は
// 会話がつながる (= 両方切ると、 普段の文字のチャットに戻る)。 会話の間に送った文には、 声で聞いている印が付く。
//
//   🔊 / 🔇 (= 外側): agent の返事を声で鳴らすか。 これだけで始めるとマイクは取らない
//   🎙 (= 内側):      マイクを開く / 閉じる。 その agent が声を聞き取る時だけ出る。 開いている間は話すだけで送られる。
//                    これだけで始めると、 声の入力だけで返事は声にしない会話になる (= 文字と app の小窓で読む)
//
// 🔊 にできるのは 1 つのタブだけで、 別のタブを見ている間も、 そのタブの会話は続く (= 返事を鳴らし、 話した文は
// そのタブへ送る)。 別のタブで 🔊 にすると、 前のタブの会話は閉じる。
//
// 色と動きで今を見せる: 🔊 は鳴らせる (= 青の枠) / 鳴っている (= 青の枠が脈打つ) / 声の engine を起こしている
// (= 薄い点滅。 起き切るまで。 起こせなければ赤の枠と理由)。 🎙 は聞いている (= 緑の枠) /
// 人が話している (= 枠が脈打つ) / 言い終えを見ている・文字にしている (= 薄い点滅) / 閉じている (= 斜線)。
// 失敗の理由はボタンの上に出る。

import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { subscribe, getSnapshot } from '../../state/voice.js'
import { useT } from '../../i18n/t.js'
import { subscribe as onVolume, getSnapshot as volumeOf, VOLUME_MAX } from '../../state/voiceVolume.js'
import { toggleVoice, toggleMic, refreshVoiceAvailable, changeVolume } from './voice.js'
import { watchEngine } from './engineWatch.js'
import './VoiceButtons.css'

// 🔊 をこの長さ押し続けると、 声の大きさのつまみが出る (= iOS の長押しのメニューより先に出す)
const LONG_PRESS_MS = 450
// つまみを閉じるために 🔊 を押した時、 その押下の click とみなす間 (= 押してから click が届くまでの時間の上限)
const CLOSING_CLICK_MS = 1000

// 🔊 の今。 切 > 声の engine を起こしている (= 起き切るまで) > 鳴っている > 入
export function speakerState({ speaking, replying, engine }) {
  if (!speaking) return 'off'
  if (engine === 'asleep' || engine === 'waking') return 'waking'
  return replying ? 'replying' : 'on'
}

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

  const speaking = !!(sid && voice.available[sid] && voice.on[sid] && !voice.quiet[sid])
  // 🔊 が入っている間だけ、 使う時だけ起こす engine の今を読み直す (= 切った時・タブが替わった時・外れた時に止める)
  useEffect(() => (speaking ? watchEngine(sid) : undefined), [sid, speaking])

  if (!sid || !voice.available[sid]) return null
  const engine = voice.engine[sid] || null
  const voiceState = speakerState({ speaking, replying: !!voice.speaking[sid], engine })
  // マイクが開いているかは、 会話の今 (= phase) が在るかで決まる
  const micState = voice.phase[sid] || 'muted'
  // 鳴らせなかった理由が先。 無ければ、 engine を起こせなかった事
  const error = voice.error[sid] || (speaking && engine === 'failed' ? t('chat.voice_engine_failed') : '')
  return (
    <span className="voice-buttons">
      {voice.listen[sid] && (
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
        aria-pressed={speaking}
        aria-label={t('chat.voice_label')}
        title={t(`chat.voice_${voiceState}`)}
        data-testid="chat-voice-button"
        data-state={voiceState}
      >
        {speaking ? '🔊' : '🔇'}
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
