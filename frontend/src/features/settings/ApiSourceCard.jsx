// The settings of a program that lists API tabs, on the settings screen's accounts section after the wallets. The fields
// are the ones the program declares in its tab list file (label, unit, range); the client writes only those, into the
// settings file its own configuration names. The program reads the file when it next handles something, so the tabs
// show a change (a new window, a new limit) once the program has written its tab list again.
import { useMemo } from 'react'
import { useT } from '../../i18n/t.js'
import { NumberField, SaveBar } from './SettingsFields.jsx'
import { useCardSave } from './useCardSave.js'
import { useDraft } from './useDraft.js'
import { useReportDirty } from './SettingsDirty.js'
import { sourceDraftOf, sourcePatch } from './apiSourceDraft.js'

function rangeOf(field) {
  const step = field.step === null || field.step === undefined ? '' : ` / ${field.step}`
  return `${field.min} – ${field.max}${step}`
}

export default function ApiSourceCard({ source, onSave }) {
  const t = useT()
  const [draft, setDraft] = useDraft(sourceDraftOf(source), JSON.stringify([source.fields, source.values]))
  const save = useMemo(() => values => onSave(source.id, values), [onSave, source.id])
  const { saving, reasons, saved, run } = useCardSave(save)
  const { values, invalid } = useMemo(() => sourcePatch(source, draft), [source, draft])
  useReportDirty(`api-source:${source.id}`, values !== null || invalid.length > 0)
  return (
    <section className="settings-card" data-testid={`settings-api-source-${source.id}`}>
      <header className="settings-card-head">
        <span className="settings-card-name">{source.id}</span>
        <span className="settings-badge">{t('settings.api_source.badge')}</span>
      </header>
      {source.tabs_unreadable && (
        <div className="settings-note warn" data-testid="settings-api-source-tabs-unreadable">
          {t('settings.api_source.tabs_unreadable', { reason: source.tabs_unreadable })}
        </div>
      )}
      {source.problem && (
        <div className="settings-note" data-testid="settings-api-source-problem">
          {t(`settings.api_source.${source.problem}`, { reason: source.reason ?? '' })}
        </div>
      )}
      {source.fields.length > 0 && (
        <>
          <div className="settings-block">
            {source.fields.map(field => (
              <NumberField
                key={field.key}
                label={field.label} suffix={field.unit ?? undefined} value={draft[field.key] ?? ''}
                onChange={value => setDraft(prev => ({ ...prev, [field.key]: value }))}
                invalid={invalid.includes(field.key)} error={t('settings.api_source.range', { range: rangeOf(field) })}
                title={rangeOf(field)} testId={`settings-api-source-field-${field.key}`}
              />
            ))}
          </div>
          <div className="settings-note">{t('settings.api_source.hint')}</div>
          <SaveBar dirty={values !== null} invalid={invalid.length > 0} saving={saving} saved={saved} reasons={reasons}
            onSave={() => run(values)} testId="settings-api-source-save" />
        </>
      )}
    </section>
  )
}
