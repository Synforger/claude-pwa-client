// StorageWarning の自己完結 host (= W2 Phase F-4 + 残骸 sweep、 2026-06-29)。 旧 AppShell.jsx の
// `useStorageQuota` 呼出 + `storageWarnDismissed` useState + `<StorageWarning ... />` render を
// 物理移送、 ロジック改変ゼロ。 Layout からは <StorageWarningHost /> 1 行配置のみ。
//
// CSS は同 dir 内に同居 (= 残骸 sweep で `layout/StorageWarning.css` から `features/status-bar/StorageWarning.css`
// に移送、 ADR-010 features 自己完結性を真に達成)。 旧 `layout/StorageWarning.jsx` 本体は Phase F-6 で削除済。

import { useState } from 'react'
import { useStorageQuota } from './useStorageQuota.js'
import './StorageWarning.css'

// しきい値: 85% で表示。 タップで隠せる (セッション中だけ)。 旧 layout/StorageWarning.jsx と同値。
const WARN_RATIO = 0.85

function fmtMB(bytes) {
  return (bytes / 1024 / 1024).toFixed(1) + 'MB'
}

export default function StorageWarningHost() {
  const info = useStorageQuota()
  const [dismissed, setDismissed] = useState(false)
  if (!info || dismissed) return null
  if (info.ratio < WARN_RATIO) return null
  const pct = Math.round(info.ratio * 100)
  return (
    <div className="storage-warn">
      <span className="storage-warn-icon">⚠</span>
      <span className="storage-warn-text">
        ストレージ使用率 {pct}% ({fmtMB(info.usage)} / {fmtMB(info.quota)})
        <span className="storage-warn-hint">不要な会話を削除すると解消します</span>
      </span>
      <button className="storage-warn-close" onClick={() => setDismissed(true)} aria-label="閉じる">×</button>
    </div>
  )
}
