import { memo } from 'react'
import { useT } from '../../i18n/t.js'
import './AskUserQuestionBubble.css'

// AskUserQuestion の Q&A を chat log に折りたたみで残す**非対話**コンポーネント。
//
// 2026-07-06 統合: 回答 UI は prompt detector の banner (= PromptStateBanner +
// PromptReplyControls) に一本化した。 従来はこの bubble にも選択肢 button / 自由記述
// input があり、 同じ質問に UI が 2 つ出る二重表示 + 「推論停止中も対話 UI が出っ放し」
// の原因だった。 ここは「何を聞かれて何を答えたか」 の履歴 (= 意味構造: header /
// description / multiSelect は画面 excerpt に無いのでここが真値) だけを担う。
// 回答経路 = banner の数字 / Space / Enter button、 自由記述はチャット入力欄からの通常送信。

// Claude が AskUserQuestion に渡してくる options の形が想定外のときも落ちないよう正規化
function normalizeOption(opt) {
  if (typeof opt === 'string') return { label: opt, description: '' }
  if (!opt || typeof opt !== 'object') return { label: String(opt ?? ''), description: '' }
  const label = typeof opt.label === 'string' ? opt.label : (opt.label != null ? String(opt.label) : '')
  const description = typeof opt.description === 'string'
    ? opt.description
    : (opt.description != null ? JSON.stringify(opt.description) : '')
  return { label, description }
}

function AskUserQuestionBubble({ askUserQuestion }) {
  const t = useT()
  const { questions, answered, selectedAnswer } = askUserQuestion
  const q = questions?.[0]
  if (!q) return null

  const options = Array.isArray(q.options) ? q.options.map(normalizeOption).filter(o => o.label) : []
  const questionText = typeof q.question === 'string' ? q.question : JSON.stringify(q.question ?? '')
  const headerText = typeof q.header === 'string' ? q.header : ''

  // 回答済 / 未回答とも同じ折りたたみログ形。 未回答は summary が「回答待ち」 になるだけで、
  // 展開すると質問全文 + 選択肢 (+ description) が読める (= banner の excerpt には
  // description が無いので、 詳しく読みたい時にここを開く)。
  const summaryText = answered
    ? t('ask.answered', {
        answer: (selectedAnswer || t('ask.answered_short')).length > 60
          ? (selectedAnswer || t('ask.answered_short')).slice(0, 60) + '…'
          : (selectedAnswer || t('ask.answered_short')),
      })
    : t('ask.waiting')

  return (
    <details
      className={`ask-question ${answered ? 'answered' : 'waiting'}`}
      data-testid="ask-user-question-bubble"
    >
      <summary className="ask-summary">{summaryText}</summary>
      <div className="ask-answered-body">
        {headerText && <div className="ask-header">{headerText}</div>}
        <div className="ask-text" data-testid="ask-user-question-text">{questionText}</div>
        {options.length > 0 && (
          <ul className="ask-option-log">
            {options.map((opt, i) => (
              <li key={i} className="ask-option-log-item">
                <span className="ask-option-label">{i + 1}. {opt.label}</span>
                {opt.description && <span className="ask-option-desc"> · {opt.description}</span>}
              </li>
            ))}
          </ul>
        )}
        {answered && selectedAnswer && (
          <div className="ask-answered-detail">{t('ask.answered_detail', { answer: selectedAnswer })}</div>
        )}
      </div>
    </details>
  )
}

export default memo(AskUserQuestionBubble)
