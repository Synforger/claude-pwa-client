import { useState, useSyncExternalStore } from 'react'
import { useT } from '../../i18n/t.js'
import { subscribe, getSnapshot, setAnswerDraft } from '../../state/tickets.js'
import { fetchTicket, postAnswer, postHolder, postSeen } from './ticketApi.js'
import { answerLanded, draftState, lowerArea } from './ticketLower.js'

// 票の画面の下の欄 (= 何を出すかは ticketLower.js の表)。 答える・渡す・確かめた の 3 つの操作を持ち、 どれも済んだら票を読み直す。
// 問いと推奨は上の件の並び (= 「訊いた」 の件) に出ているので、 ここには答えの欄と操作だけを置く (= 同じ問いを 2 度出さない)。

const ERROR_CHANGED = 'ticket_ask_changed'
const ERROR_NOT_WAITING = 'ticket_not_waiting'

export default function TicketLower({ ticketId, detail, candidates, reload }) {
  const t = useT()
  const area = lowerArea(detail)
  const { answerDrafts } = useSyncExternalStore(subscribe, getSnapshot)
  const draft = answerDrafts[ticketId]
  const askedAt = area.asked ? area.asked.at : null
  const draftKind = draftState(draft, askedAt)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [holderId, setHolderId] = useState('')

  const act = async (work) => {
    setBusy(true)
    setMessage('')
    try {
      await work()
    } catch (error) {
      setMessage(error?.message || t('ticket.error_unknown'))
    } finally {
      setBusy(false)
    }
  }

  const submit = (recommend) => act(async () => {
    try {
      await postAnswer(ticketId, askedAt, { text: draft?.text ?? '', recommend })
      setAnswerDraft(ticketId, askedAt, '')
      reload()
    } catch (error) {
      if (error?.code === ERROR_CHANGED) {
        // 見ていた問いが替わった: 下書きは残し、 新しい問いを読み直す (= 下書きは「前の問いへの下書き」 になる)
        reload()
      } else if (error?.code === ERROR_NOT_WAITING) {
        // 返事が網で落ちて押し直したなら、 1 回目の答えは受かっている
        const fresh = await fetchTicket(ticketId).catch(() => null)
        if (fresh && answerLanded(fresh, askedAt)) {
          setAnswerDraft(ticketId, askedAt, '')
          reload()
          return
        }
      }
      throw error
    }
  })

  const handOver = () => act(async () => {
    await postHolder(ticketId, holderId)
    reload()
  })

  const confirmSeen = () => act(async () => {
    await postSeen(ticketId)
    reload()
  })

  const parts = []
  if (area.noHolder) {
    parts.push(
      <section key="holder" className="ticket-lower-block" data-testid="ticket-no-holder">
        <div className="ticket-lower-title">{t('ticket.no_holder')}</div>
        <div className="ticket-handover">
          <select value={holderId} onChange={(e) => setHolderId(e.target.value)} disabled={busy} aria-label={t('ticket.pick_holder')} data-testid="ticket-holder-select">
            <option value="">{t('ticket.pick_holder')}</option>
            {candidates.map((tab) => <option key={tab.id} value={tab.id}>{tab.title}</option>)}
          </select>
          <button type="button" className="ticket-button" onClick={handOver} disabled={busy || !holderId} data-testid="ticket-hand-over">
            {t('ticket.hand_over')}
          </button>
        </div>
      </section>,
    )
  }
  if (area.asked) {
    parts.push(
      <section key="answer" className="ticket-lower-block" data-testid="ticket-answer-box">
        {draftKind === 'previous' && (
          <div className="ticket-draft-previous" data-testid="ticket-draft-previous">
            <div className="ticket-lower-title">{t('ticket.draft_previous')}</div>
            <div className="ticket-draft-previous-text">{draft.text}</div>
            <button type="button" className="ticket-button" onClick={() => setAnswerDraft(ticketId, askedAt, draft.text)} data-testid="ticket-draft-use">
              {t('ticket.draft_use')}
            </button>
          </div>
        )}
        <textarea
          className="ticket-answer-field"
          value={draftKind === 'current' ? draft.text : ''}
          onChange={(e) => setAnswerDraft(ticketId, askedAt, e.target.value)}
          placeholder={t('ticket.answer_placeholder')}
          rows={3}
          disabled={busy}
          data-testid="ticket-answer-field"
        />
        <div className="ticket-answer-buttons">
          {area.hasRecommend && (
            <button type="button" className="ticket-button" onClick={() => submit(true)} disabled={busy} data-testid="ticket-answer-recommend">
              {t('ticket.answer_recommend')}
            </button>
          )}
          <button type="button" className="ticket-button ticket-button-primary" onClick={() => submit(false)}
            disabled={busy || draftKind !== 'current'} data-testid="ticket-answer-send">
            {t('ticket.answer_send')}
          </button>
        </div>
      </section>,
    )
  }
  if (area.pending.length > 0) {
    parts.push(
      <section key="pending" className="ticket-lower-block ticket-delivering" data-testid="ticket-delivering">
        <div className="ticket-lower-title">{t(area.closedPending ? 'ticket.delivering_closed' : 'ticket.delivering')}</div>
        {area.pending.length > 1 && (
          <ul className="ticket-delivering-list">
            {area.pending.map((at) => <li key={at}>{t('ticket.delivering_for', { time: new Date(at).toLocaleString() })}</li>)}
          </ul>
        )}
      </section>,
    )
  }
  if (area.problem) {
    parts.push(
      <section key="problem" className="ticket-lower-block ticket-problem" data-testid="ticket-problem">
        <div className="ticket-lower-title ticket-problem-title">{t(`ticket.problem_${area.problem}`)}</div>
        <button type="button" className="ticket-button" onClick={confirmSeen} disabled={busy} data-testid="ticket-seen">
          {t('ticket.seen')}
        </button>
      </section>,
    )
  }
  if (parts.length === 0 && !message) return null
  return (
    <div className="ticket-lower" data-testid="ticket-lower">
      {parts}
      {message && <div className="ticket-error" role="alert" data-testid="ticket-error">{message}</div>}
    </div>
  )
}
