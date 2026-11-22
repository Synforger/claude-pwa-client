// A tool input printed in full, one monospace block per part, with line breaks kept and nothing folded or cut.
// Used by PermissionWindowDialog.jsx.
import { useT } from '../../i18n/t.js'

/** @param {{fields: import('./windowView.js').InputField[], label?: string, testId: string}} props
 *  `label` heads the group when the window shows two inputs side by side (the one that runs, the one the record holds) */
export default function WindowInput({ fields, label, testId }) {
  const t = useT()
  return (
    <section className="permission-window-input-group" data-testid={testId}>
      {label && <div className="permission-window-input-label">{label}</div>}
      {fields.length === 0 && <div className="permission-window-no-input">{t('permission_window.no_input')}</div>}
      {fields.map(field => (
        <div key={field.name ?? ''} className="permission-window-field">
          {field.name && <div className="permission-window-field-name">{field.name}</div>}
          <pre className="permission-window-input">{field.text}</pre>
        </div>
      ))}
    </section>
  )
}
