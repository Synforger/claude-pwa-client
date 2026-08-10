import { useState } from 'react'
import { useT } from '../../i18n/t.js'
import { useMeetings, useMeeting } from './useMeetings.js'
import MeetingBoard from './MeetingBoard.jsx'
import './MeetingsPanel.css'

// 会議タブの中身。 上に会議の一覧、 選ぶと下に掲示板が出る。
//
// 会議は階層ごとに置かれるので、 一覧は階層でまとめて出す。 終了した会議も同じ
// 一覧に残す (= 前回の議論が、 何もしなくても見える状態を既定にする)。

function groupByTier(meetings) {
  const groups = new Map()
  for (const m of meetings) {
    if (!groups.has(m.tier)) groups.set(m.tier, [])
    groups.get(m.tier).push(m)
  }
  return [...groups.entries()]
}

export default function MeetingsPanel() {
  const t = useT()
  const { meetings, configured, reload: reloadList } = useMeetings()
  const [selectedId, setSelectedId] = useState(null)
  const { meeting, reload: reloadMeeting } = useMeeting(selectedId)

  if (!configured) {
    return <p className="meetings-empty">{t('meetings.notConfigured')}</p>
  }
  if (meetings === null) {
    return <p className="meetings-empty">{t('meetings.loading')}</p>
  }
  if (meetings.length === 0) {
    return <p className="meetings-empty">{t('meetings.none')}</p>
  }

  return (
    <div className="meetings-panel">
      <div className="meetings-list">
        {groupByTier(meetings).map(([tier, items]) => (
          <section key={tier} className="meetings-tier">
            <h3 className="meetings-tier-name">{tier}</h3>
            <ul>
              {items.map(m => (
                <li key={m.id}>
                  <button
                    type="button"
                    className={`meetings-item is-${m.state}${m.id === selectedId ? ' is-selected' : ''}`}
                    onClick={() => setSelectedId(m.id)}
                  >
                    <span className="meetings-item-topic">{m.topic}</span>
                    <span className="meetings-item-state">{t(`meetings.state.${m.state}`)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>

      {meeting ? (
        <MeetingBoard
          meeting={meeting}
          onPosted={() => {
            reloadMeeting()
            reloadList()
          }}
        />
      ) : (
        <p className="meetings-empty">{t('meetings.pick')}</p>
      )}
    </div>
  )
}
