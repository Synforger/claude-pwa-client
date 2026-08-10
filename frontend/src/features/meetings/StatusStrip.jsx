import { useT } from '../../i18n/t.js'

// 参加者の現在地。 誰が止まっているか、 そして「いつ掲示板を読んだか」 を出す。
//
// 読んだ時刻を見せるのが肝。 参加者は作業中ずっと掲示板を見ているわけではなく、
// 区切りに来た時だけ読む。 その時刻が出ていないと、 いま書いた指示が相手に届いて
// いるのかどうかが、 画面からは永久に分からない。

// 回避中 = 異議を出したまま、 裁定を待たずに回避して進んでいる状態。 止まってはいない
// が、 裁定が返ったら回避を外して測り直す必要があるので、 進行中とは分けて出す。
const TONE_BY_STATE = [
  [/異議|objection/i, 'objection'],
  [/回避|workaround/i, 'workaround'],
  [/待機|wait/i, 'waiting'],
  [/完了|done|complete/i, 'done'],
  [/進行|running|active/i, 'running'],
]

export function toneFor(state) {
  const found = TONE_BY_STATE.find(([re]) => re.test(state || ''))
  return found ? found[1] : 'unknown'
}

export default function StatusStrip({ participants }) {
  const t = useT()
  if (!participants?.length) return null

  return (
    <ul className="meetings-status" aria-label={t('meetings.status')}>
      {participants.map(p => (
        <li key={p.name} className={`meetings-status-row is-${toneFor(p.state)}`}>
          <span className="meetings-status-name">{p.name}</span>
          {p.version ? <span className="meetings-status-version">{p.version}</span> : null}
          <span className="meetings-status-state">{p.state}</span>
          {p.note ? <span className="meetings-status-note">{p.note}</span> : null}
          <span className="meetings-status-read">
            {p.read_at ? t('meetings.readAt', { at: p.read_at }) : t('meetings.neverRead')}
          </span>
        </li>
      ))}
    </ul>
  )
}
