import { useState } from 'react'
import { useT } from '../../i18n/t.js'
import { postToBoard } from './useMeetings.js'
import StatusStrip from './StatusStrip.jsx'

// 掲示板。 見た目は普通のチャットだが、 書けるのは 4 種類の発言だけで、 参加者同士は
// 互いに宛てて書かない。 自由記述に戻すと同調と話題逸れが入るので、 入力欄でも種類を
// 先に選ばせ、 UI の側からも 4 種を外れられないようにする。

const KINDS = ['report', 'objection', 'ruling', 'directive']

// この画面から書くのは常に運用者本人なので、 発言者名は固定でよい。
// 掲示板の側では参加者名と並ぶ 1 つの名前でしかない。
const OPERATOR = 'operator'

export default function MeetingBoard({ meeting, onPosted }) {
  const t = useT()
  const [kind, setKind] = useState('directive')
  const [body, setBody] = useState('')
  const [sending, setSending] = useState(false)
  const [failed, setFailed] = useState(false)

  const closed = meeting.state === 'archived'

  async function send(event) {
    event.preventDefault()
    const text = body.trim()
    if (!text || sending) return
    setSending(true)
    setFailed(false)
    const ok = await postToBoard(meeting.id, { who: OPERATOR, kind, body: text })
    setSending(false)
    if (!ok) {
      setFailed(true)
      return
    }
    setBody('')
    onPosted?.()
  }

  return (
    <div className="meetings-board">
      <StatusStrip participants={meeting.participants} />

      <ol className="meetings-posts">
        {meeting.posts.map((post, i) => (
          <li key={`${post.who}-${i}`} className={`meetings-post is-${post.kind}`}>
            <div className="meetings-post-head">
              <span className="meetings-post-who">{post.who}</span>
              <span className="meetings-post-at">{post.at}</span>
            </div>
            <div className="meetings-post-body">{post.body}</div>
          </li>
        ))}
      </ol>

      {closed ? (
        <p className="meetings-closed">{t('meetings.closed')}</p>
      ) : (
        <form className="meetings-compose" onSubmit={send}>
          <select
            className="meetings-kind"
            value={kind}
            onChange={e => setKind(e.target.value)}
            aria-label={t('meetings.kind')}
          >
            {KINDS.map(k => (
              <option key={k} value={k}>{t(`meetings.kind.${k}`)}</option>
            ))}
          </select>
          <input
            className="meetings-input"
            value={body}
            onChange={e => setBody(e.target.value)}
            placeholder={t('meetings.placeholder')}
          />
          <button type="submit" disabled={sending || !body.trim()}>
            {t('meetings.send')}
          </button>
          {failed ? <span className="meetings-failed">{t('meetings.sendFailed')}</span> : null}
        </form>
      )}
    </div>
  )
}
