// /task-output の raw text を fetch して表示する共有 body (= 2026-07-05)。
// TaskNotification の inline 展開が使う (= 旧 TaskOutputModal の中身を抽出して modal 退役)。
// UI は最小: ローディング / エラー / <pre> raw text。
import { useState, useEffect } from 'react'
import { apiFetch } from '../../utils/api.js'
import { useT } from '../../i18n/t.js'
import { translateHttpErrorDetail } from '../../utils/httpError.js'

export default function TaskOutputBody({ path }) {
  const t = useT()
  const [content, setContent] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    setContent(null)
    setError(null)
    apiFetch(`/task-output?path=${encodeURIComponent(path)}`, { signal: controller.signal })
      .then(async r => {
        if (r.ok) {
          const data = await r.json()
          setContent(typeof data?.content === 'string' ? data.content : '')
          return
        }
        const d = await r.json().catch(() => ({}))
        throw new Error(translateHttpErrorDetail(d?.detail, `HTTP ${r.status}`))
      })
      .catch(e => { if (e.name !== 'AbortError') setError(e.message || t('file_preview.load_error')) })
    return () => controller.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path])

  if (error) return <span className="error">{error}</span>
  if (content === null) return <span className="dim">{t('common.loading')}</span>
  return <pre className="task-output-raw">{content || t('common.empty')}</pre>
}
