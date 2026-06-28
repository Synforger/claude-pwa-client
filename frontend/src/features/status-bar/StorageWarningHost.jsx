// StorageWarning の自己完結 host (= W2 Phase F-4、 2026-06-29)。 旧 AppShell.jsx の
// `useStorageQuota` 呼出 + `storageWarnDismissed` useState + `<StorageWarning ... />` render を
// 物理移送、 ロジック改変ゼロ。 AppShell からは <StorageWarningHost /> 1 行配置のみ。
//
// 注: features → layout 層は ADR-010 / eslint-plugin-boundaries で禁止されているため、
// shared component (= layout/StorageWarning.jsx) を import せず、 JSX (= 14 行) を物理移送する。
// CSS (= layout/StorageWarning.css) は AppShell.jsx が intra-layer side-effect import で
// 引き続き load する (= boundaries 制約回避、 .storage-warn 系 class 定義は重複させない)。
// 旧 layout/StorageWarning.jsx 本体は本 phase では touch せず、 退役は別 phase に明示先送り
// (= dead file 化のみ)。

import { useState } from 'react'
import { useStorageQuota } from './useStorageQuota.js'

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
