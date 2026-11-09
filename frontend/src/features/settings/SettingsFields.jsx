// 設定の画面の入力欄と保存の帯 (= 各 section が共有する見た目)。
import { useT } from '../../i18n/t.js'

/** 数の欄 1 つ。 invalid の時は枠を赤にする (= 保存は押せない)。 */
export function NumberField({ label, value, onChange, invalid, suffix, placeholder, testId, title }) {
  return (
    <label className={`settings-field${invalid ? ' invalid' : ''}`} title={title}>
      <span className="settings-field-label">{label}</span>
      <span className="settings-field-input">
        <input
          type="text"
          inputMode="decimal"
          value={value}
          placeholder={placeholder}
          onChange={e => onChange(e.target.value)}
          aria-invalid={invalid ? 'true' : undefined}
          data-testid={testId}
        />
        {suffix && <span className="settings-field-suffix">{suffix}</span>}
      </span>
    </label>
  )
}

/** 保存の帯: 保存ボタン (= 変わりが無い・値が不正な間は押せない) と、 backend が断った理由。 */
export function SaveBar({ dirty, invalid, saving, onSave, reasons, saved, testId }) {
  const t = useT()
  return (
    <div className="settings-save-bar">
      <button
        type="button"
        className="modal-save-btn"
        disabled={!dirty || invalid || saving}
        onClick={onSave}
        data-testid={testId}
      >
        {saving ? t('settings.saving') : t('settings.save')}
      </button>
      {invalid && <span className="settings-note warn">{t('settings.invalid')}</span>}
      {saved && !dirty && !invalid && <span className="settings-note ok">{t('settings.saved')}</span>}
      {reasons.length > 0 && (
        <div className="settings-error" role="alert">
          {reasons.map(line => <div key={line}>{line}</div>)}
        </div>
      )}
    </div>
  )
}
