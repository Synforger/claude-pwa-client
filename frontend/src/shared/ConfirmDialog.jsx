// シンプルな yes/no 確認ダイアログ。背景クリックで cancel 扱い。
import { useT } from '../i18n/t.js'

export default function ConfirmDialog({ open, text, onCancel, onConfirm }) {
  const t = useT()
  if (!open) return null
  return (
    <div className="confirm-overlay" onClick={onCancel}>
      <div className="confirm-dialog" onClick={e => e.stopPropagation()}>
        <p className="confirm-text">{text}</p>
        <div className="confirm-actions">
          <button onClick={onCancel} className="confirm-btn no">{t('confirm.no')}</button>
          <button onClick={onConfirm} className="confirm-btn yes">{t('confirm.yes')}</button>
        </div>
      </div>
    </div>
  )
}
