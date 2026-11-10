// 設定の画面の「タブの眠りと入れ替え」。 エージェントごとの眠るまでの分数と入れ替えの線、 子のタブの上限数。
import { useMemo } from 'react'
import { useT } from '../../i18n/t.js'
import { NumberField, SaveBar } from './SettingsFields.jsx'
import { useCardSave } from './useCardSave.js'
import { useDraft } from './useDraft.js'
import { useReportDirty } from './SettingsDirty.js'
import { CHILD_LIMIT_RULE, agentDraftOf, agentPatch, agentRules, childLimitPatch, ruleMessage } from './settingsDraft.js'

function AgentCard({ agent, limits, onSave }) {
  const t = useT()
  const [draft, setDraft] = useDraft(agentDraftOf(agent), JSON.stringify([agent.sleep_minutes, agent.rollover]))
  const { saving, reasons, saved, run } = useCardSave(onSave)
  const { patch, invalid } = useMemo(() => agentPatch(agent, draft, limits), [agent, draft, limits])
  useReportDirty(`agent:${agent.id}`, patch !== null || invalid.length > 0)
  const rules = useMemo(() => agentRules(limits), [limits])
  const errorOf = (name) => { const m = ruleMessage(rules[name]); return t(m.key, m.vars) }
  const field = (name, label, suffix, hint) => (
    <NumberField
      label={label} suffix={suffix} value={draft[name]} title={hint}
      onChange={value => setDraft(prev => ({ ...prev, [name]: value }))}
      invalid={invalid.includes(name)} error={errorOf(name)} placeholder={t('settings.agents.blank')}
      testId={`settings-agent-${name}`}
    />
  )
  return (
    <section className="settings-card" data-testid={`settings-agent-${agent.id}`}>
      <header className="settings-card-head"><span className="settings-card-name">{agent.display_name}</span></header>
      <div className="settings-block">
        {field('sleep', t('settings.agents.sleep'), t('settings.unit.minutes'), t('settings.agents.sleep_hint'))}
      </div>
      <div className="settings-block">
        <div className="settings-block-title">{t('settings.agents.rollover')}</div>
        <div className="settings-note">{t('settings.agents.rollover_hint')}</div>
        {field('working', t('settings.agents.working'), '%')}
        {field('idleContext', t('settings.agents.idle_context'), '%')}
        {field('idleMinutes', t('settings.agents.idle_minutes'), t('settings.unit.minutes'))}
      </div>
      <SaveBar dirty={patch !== null} invalid={invalid.length > 0} saving={saving} saved={saved} reasons={reasons}
        onSave={() => run(patch)} testId="settings-agent-save" />
    </section>
  )
}

function ChildLimit({ value, onSave }) {
  const t = useT()
  const current = value === null || value === undefined ? '' : String(value)
  const [text, setText] = useDraft(current, current)
  const { saving, reasons, saved, run } = useCardSave(onSave)
  const { patch, invalid } = useMemo(() => childLimitPatch(value, text), [value, text])
  useReportDirty('child-limit', patch !== null || invalid.length > 0)
  const message = ruleMessage(CHILD_LIMIT_RULE)
  return (
    <section className="settings-card" data-testid="settings-child-limit">
      <NumberField
        label={t('settings.agents.child_limit')} value={text} onChange={setText} invalid={invalid.length > 0}
        error={t(message.key, message.vars)}
        placeholder={t('settings.agents.child_limit_none')} testId="settings-child-limit-input" title={t('settings.agents.child_limit_hint')}
      />
      <div className="settings-note">{t('settings.agents.child_limit_hint')}</div>
      <SaveBar dirty={patch !== null} invalid={invalid.length > 0} saving={saving} saved={saved} reasons={reasons}
        onSave={() => run(patch)} testId="settings-child-limit-save" />
    </section>
  )
}

export default function AgentsSection({ view, onSave }) {
  const t = useT()
  return (
    <section className="settings-section" data-testid="settings-agents">
      <h3>{t('settings.agents.title')}</h3>
      {view.agents.map(agent => (
        <AgentCard key={agent.id} agent={agent} limits={view.limits} onSave={onSave} />
      ))}
      <ChildLimit value={view.child_sessions_max} onSave={onSave} />
    </section>
  )
}
