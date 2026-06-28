import { useState, useEffect, useRef, useSyncExternalStore } from 'react'
import MessageRenderer from '../chat/MessageRenderer.jsx'
import { formatTool } from '../../utils/format.js'
import { apiFetch } from '../../utils/api.js'
import { useEscape } from '../../hooks/useEscape.js'
import { subagentsSse } from '../../transport/sse-subagents.ts'
import {
  subscribe as subscribeSessions,
  getSnapshot as getSessionsSnapshot,
} from '../../state/sessions.js'
import {
  subscribe as subscribeUi,
  getSnapshot as getUiSnapshot,
  setOverlay,
} from '../../state/ui.js'
import '../../shared/Modal.css'
import './SubagentsModal.css'

// サブエージェント (= Task で起動した子 agent) + Workflow run の一覧と transcript を見るモーダル。
// 親 chat には sidechain を出さない方針なので、 中身を遡りたい時の専用ビュー。
// 3 階層: 一覧 (Task agent + Workflow run) → Workflow の agent 一覧 → 個別 transcript。
// 105 agent 規模でも Workflow は 1 行に畳まれ、 開いた時だけ中の agent を展開する。

function fmtTokens(n) {
  if (typeof n !== 'number') return null
  if (n < 1000) return `${n}`
  if (n < 1_000_000) return `${(n / 1000).toFixed(0)}k`
  return `${(n / 1_000_000).toFixed(1)}M`
}
function fmtDuration(ms) {
  if (typeof ms !== 'number') return null
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m${String(s % 60).padStart(2, '0')}s`
}

function StatusChip({ done, status }) {
  const label = status || (done ? 'done' : 'running')
  const cls = done || ['completed', 'killed', 'error'].includes(status) ? 'sa-done' : 'sa-running'
  return <span className={`sa-chip ${cls}`}>{label}</span>
}

// transcript 1 event を軽量描画する (= 親 chat の MessageItem 完全再現はしない、 要点だけ)。
function TranscriptEvent({ event }) {
  if (event.type === 'user_message') {
    return (
      <div className="sa-ev sa-ev-user">
        <span className="sa-ev-role">▸ prompt</span>
        <div className="sa-ev-text"><MessageRenderer text={event.text || ''} /></div>
      </div>
    )
  }
  if (event.type === 'assistant') {
    const content = event.message?.content || []
    const texts = content.filter(b => b.type === 'text').map(b => b.text).join('')
    const thinking = content.filter(b => b.type === 'thinking').map(b => b.thinking).join('\n')
    const tools = content
      .filter(b => b.type === 'tool_use' && b.name !== 'AskUserQuestion')
      .map(b => formatTool(b))
    return (
      <div className="sa-ev sa-ev-agent">
        {thinking && <div className="sa-ev-thinking">{thinking}</div>}
        {texts && <div className="sa-ev-text"><MessageRenderer text={texts} /></div>}
        {tools.map(t => (
          <div key={t.id} className="sa-ev-tool">{t.shortLabel || t.name}</div>
        ))}
      </div>
    )
  }
  return null
}

function TranscriptView({ sid, agent, onBack }) {
  const [events, setEvents] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    setEvents(null)
    setError(null)
    const wfq = agent.wf ? `?wf=${encodeURIComponent(agent.wf)}` : ''
    apiFetch(
      `/sessions/${encodeURIComponent(sid)}/subagents/${encodeURIComponent(agent.agentId)}/transcript${wfq}`,
      { signal: controller.signal },
    )
      .then(r => (r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`)))
      .then(data => setEvents(data.events || []))
      .catch(e => { if (e.name !== 'AbortError') setError('transcript を読めませんでした') })
    return () => controller.abort()
  }, [sid, agent.agentId, agent.wf])

  return (
    <div className="sa-transcript">
      <button className="sa-back" onClick={onBack}>← 戻る</button>
      <div className="sa-detail-head">
        <span className="sa-detail-desc">{agent.label || agent.description || agent.agentId}</span>
        <StatusChip done={agent.done} />
      </div>
      {error && <span className="error">{error}</span>}
      {events === null && !error && <span className="dim">読み込み中…</span>}
      {events && events.length === 0 && <span className="dim">(まだ出力がありません)</span>}
      {events && events.map((ev, i) => <TranscriptEvent key={i} event={ev} />)}
    </div>
  )
}

function WorkflowAgentsView({ sid, run, onBack, onOpenAgent }) {
  const [agents, setAgents] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    setAgents(null)
    setError(null)
    apiFetch(`/sessions/${encodeURIComponent(sid)}/workflows/${encodeURIComponent(run.runId)}/agents`,
      { signal: controller.signal })
      .then(r => (r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`)))
      .then(data => setAgents(data.agents || []))
      .catch(e => { if (e.name !== 'AbortError') setError('agent 一覧を読めませんでした') })
    return () => controller.abort()
  }, [sid, run.runId])

  const doneCount = agents ? agents.filter(a => a.done).length : 0

  return (
    <div>
      <button className="sa-back" onClick={onBack}>← 一覧へ</button>
      <div className="sa-detail-head">
        <span className="sa-detail-desc">{run.workflowName || run.runId}</span>
        <StatusChip status={run.status} done />
      </div>
      <div className="sa-run-meta">
        {agents && `${agents.length} agents ・ done ${doneCount}`}
        {fmtTokens(run.totalTokens) && ` ・ ${fmtTokens(run.totalTokens)} tok`}
        {fmtDuration(run.durationMs) && ` ・ ${fmtDuration(run.durationMs)}`}
      </div>
      {run.phaseTitles?.length > 0 && (
        <div className="sa-run-phases">{run.phaseTitles.join(' → ')}</div>
      )}
      {error && <span className="error">{error}</span>}
      {agents === null && !error && <span className="dim">読み込み中…</span>}
      {agents && (
        <ul className="sa-list">
          {agents.map((a, i) => (
            <li key={a.agentId} className="sa-item" onClick={() => onOpenAgent({ ...a, wf: run.runId })}>
              <div className="sa-item-main">
                <span className="sa-item-idx">#{i + 1}</span>
                <span className="sa-item-desc">{a.label || a.agentId}</span>
                <StatusChip done={a.done} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function SubagentsModal() {
  // W2 Phase E-2 自己解決: sid = activeId / focus = ui.overlays.subagentsFocus / onClose = setOverlay
  // (= AppShell からの props 渡しを撤去、 OverlayHost が引数なしで render する)。
  const sessionsSnap = useSyncExternalStore(subscribeSessions, getSessionsSnapshot)
  const uiSnap = useSyncExternalStore(subscribeUi, getUiSnapshot)
  const sid = sessionsSnap.activeId
  const focus = uiSnap.overlays.subagentsFocus
  const onClose = () => setOverlay('subagents', false)
  // activeSid 不在時は何も render しない (= 旧 AppShell ガード `&& activeSid` と同等)
  if (!sid) return null
  return <SubagentsModalInner sid={sid} focus={focus} onClose={onClose} />
}

function SubagentsModalInner({ sid, focus, onClose }) {
  const [data, setData] = useState(null)  // {subagents, workflows}
  const [error, setError] = useState(null)
  const [run, setRun] = useState(null)        // drill-down 中の Workflow run
  const [agent, setAgent] = useState(null)    // transcript 表示中の agent
  const focusedRef = useRef(false)            // focus 自動遷移を 1 回だけ行う

  // SSE 接続: backend が subagents/workflows ディレクトリを 1 秒間隔で監視、 変化を検知
  // したら最新 payload を push する。 polling より精密で、 走り終わった瞬間に done に
  // 切り替わる。 接続切れは EventSource が auto-reconnect (= 3 秒)。
  useEffect(() => {
    setError(null)
    // /sessions/{sid}/subagents/stream は transport/sse-subagents.ts per-sid factory (= ADR-019) で
    // 立てる。 subscribe は sid 単位で同 EventSource 共有 (= refs カウンタ)、 unsubscribe で自動 close。
    const unsub = subagentsSse.subscribe(sid, (d) => {
      if (d && typeof d === 'object') {
        setData({ subagents: d.subagents || [], workflows: d.workflows || [] })
      }
    })
    return () => { unsub() }
  }, [sid])

  // チップから渡された focus で、 一覧ロード後に該当 run / agent へ 1 回だけ自動遷移する。
  //   - workflowTaskId : tool_result の "Task ID" が manifest.taskId と一致する run を開く
  //   - agentDesc      : Task の description が一致する subagent の transcript を直接開く
  useEffect(() => {
    if (!focus || !data || focusedRef.current) return
    if (focus.kind === 'workflowTaskId') {
      const w = data.workflows.find(x => x.taskId === focus.value)
      if (w) { setRun(w); focusedRef.current = true }
    } else if (focus.kind === 'agentDesc') {
      const s = data.subagents.find(x => x.description === focus.value)
      if (s) { setAgent(s); focusedRef.current = true }
    }
  }, [focus, data])

  // Escape の動作 = 戻る (= drill-down → 一覧 → 閉じる) の階層下げ (= F-29 集約)
  useEscape(() => {
    if (agent) setAgent(null)
    else if (run) setRun(null)
    else onClose()
  })

  const subagents = data?.subagents || []
  const workflows = data?.workflows || []
  const isEmpty = data && subagents.length === 0 && workflows.length === 0

  return (
    <div className="modal-overlay" onClick={onClose} data-testid="subagents-modal">
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span className="modal-path">Subagents</span>
          <div className="modal-actions">
            {/* SSE で常時 live 同期するため手動 reload ボタンは不要 (2026-06-12) */}
            <button className="modal-close" onClick={onClose}>✕</button>
          </div>
        </div>
        <div className="modal-body">
          {error && <span className="error">{error}</span>}
          {agent ? (
            <TranscriptView sid={sid} agent={agent} onBack={() => setAgent(null)} />
          ) : run ? (
            <WorkflowAgentsView sid={sid} run={run} onBack={() => setRun(null)} onOpenAgent={setAgent} />
          ) : data === null && !error ? (
            <span className="dim">読み込み中…</span>
          ) : isEmpty ? (
            <span className="dim">このセッションでは、 まだサブエージェントは起動していません。</span>
          ) : (
            <>
              {workflows.length > 0 && (
                <>
                  <div className="sa-section">Workflows</div>
                  <ul className="sa-list">
                    {workflows.map(w => (
                      <li key={w.runId} className="sa-item sa-wf" onClick={() => setRun(w)}>
                        <div className="sa-item-main">
                          <span className="sa-item-desc">⚙ {w.workflowName || w.runId}</span>
                          <StatusChip status={w.status} done />
                        </div>
                        <div className="sa-item-sub">
                          {w.agentCount != null && <span>{w.agentCount} agents</span>}
                          {fmtTokens(w.totalTokens) && <span>・ {fmtTokens(w.totalTokens)} tok</span>}
                          {fmtDuration(w.durationMs) && <span>・ {fmtDuration(w.durationMs)}</span>}
                        </div>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {subagents.length > 0 && (
                <>
                  {workflows.length > 0 && <div className="sa-section">Task subagents</div>}
                  <ul className="sa-list">
                    {subagents.map(s => (
                      <li key={s.agentId} className="sa-item" onClick={() => setAgent(s)}>
                        <div className="sa-item-main">
                          <span className="sa-item-desc">{s.description || s.agentId}</span>
                          <StatusChip done={s.done} />
                        </div>
                        <div className="sa-item-sub">
                          {s.agentType && <span className="sa-item-type">{s.agentType}</span>}
                          {s.lastTool && <span className="sa-item-tool">・ {s.lastTool}</span>}
                        </div>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
