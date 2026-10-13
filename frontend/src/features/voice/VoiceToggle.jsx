// 上部の 🔊: このタブの返事を声で聞くかの切り替え。 声を持つ agent のタブにだけ出る。
// ON の間は、 新しく届いた返事を文ごとに鳴らす。 OFF にすると、 鳴っている音もその場で止まる。

import { useEffect, useSyncExternalStore } from 'react'
import { subscribe, getSnapshot } from '../../state/voice.js'
import { useT } from '../../i18n/t.js'
import { setVoice, refreshVoiceAvailable } from './voice.js'
import './VoiceToggle.css'

export default function VoiceToggle({ sid }) {
  const voice = useSyncExternalStore(subscribe, getSnapshot)
  const t = useT()

  useEffect(() => { if (sid) refreshVoiceAvailable(sid) }, [sid])

  if (!sid || !voice.available[sid]) return null
  const on = !!voice.on[sid]
  const error = voice.error[sid] || ''
  return (
    <span className="voice-toggle-wrap">
      <button
        className={`screen-toggle${on ? ' active' : ''}${error ? ' failed' : ''}`}
        onClick={() => setVoice(sid, !on)}
        aria-pressed={on}
        aria-label={t('topbar.voice_label')}
        title={on ? t('topbar.voice_off') : t('topbar.voice_on')}
        data-testid="voice-toggle"
      >
        {on ? '🔊' : '🔇'}
      </button>
      {error && <span className="voice-error" role="alert" data-testid="voice-error">{error}</span>}
    </span>
  )
}
