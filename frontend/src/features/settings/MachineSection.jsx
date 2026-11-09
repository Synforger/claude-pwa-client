// 設定の画面の「この機械」。 アプリの更新と backend の再起動 (= 操作) と、 動いている版・backend の起動時刻・
// 止まりの見張りの最後の記録 (= 見るだけ)。
import { useT } from '../../i18n/t.js'
import ConfirmDialog from '../../_common/ConfirmDialog.jsx'
import { useMachineActions } from './useMachineActions.js'
import { formatMoment } from './settingsDraft.js'

function Fact({ label, value, testId }) {
  return (
    <div className="settings-fact">
      <span className="settings-fact-label">{label}</span>
      <span className="settings-fact-value" data-testid={testId}>{value}</span>
    </div>
  )
}

function stallText(t, stall) {
  if (!stall) return t('settings.machine.stall_none')
  return t('settings.machine.stall_last', { back_at: stall.back_at.replace('T', ' '), sec: stall.stood_still_sec })
}

export default function MachineSection({ view }) {
  const t = useT()
  const machine = view.machine
  const actions = useMachineActions()
  return (
    <section className="settings-section" data-testid="settings-machine">
      <h3>{t('settings.machine.title')}</h3>
      <section className="settings-card">
        <div className="settings-block">
          <button type="button" className="modal-edit-btn settings-wide" onClick={actions.refreshApp}
            disabled={actions.refreshing} title={t('drawer.menu.update_app_title')} data-testid="settings-update-app">
            {t('drawer.menu.update_app')}
            {actions.runningBuild && (
              <span className="settings-build" data-testid="running-build">build {actions.runningBuild}</span>
            )}
          </button>
          {actions.restartable && (
            <button type="button" className="modal-edit-btn settings-wide" onClick={() => actions.setRestartConfirm(true)}
              title={t('drawer.menu.restart_backend_title')} data-testid="restart-backend">
              {t('drawer.menu.restart_backend')}
            </button>
          )}
          {actions.restartError && (
            <div className="settings-error" role="alert">{t('drawer.restart.failed', { reason: actions.restartError })}</div>
          )}
        </div>
        <div className="settings-block">
          <Fact label={t('settings.machine.version')} value={machine.version ?? '—'} testId="settings-version" />
          <Fact label={t('settings.machine.started_at')} value={formatMoment(machine.backend_started_at)}
            testId="settings-started-at" />
          <Fact label={t('settings.machine.stall')} value={stallText(t, machine.loop_stall)} testId="settings-stall" />
        </div>
      </section>
      {actions.restarting && (
        <div className="backend-restart-banner" role="status" data-testid="backend-restarting">
          {t('drawer.restart.in_progress')}
        </div>
      )}
      <ConfirmDialog
        open={actions.restartConfirm}
        text={t('drawer.restart.confirm')}
        onCancel={() => actions.setRestartConfirm(false)}
        onConfirm={actions.restart}
      />
    </section>
  )
}
