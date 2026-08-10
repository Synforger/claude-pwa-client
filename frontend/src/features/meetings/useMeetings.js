import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '../../utils/api.js'

// 会議 (= 並列エージェントの掲示板) を backend から取る。
//
// 真値は backend が読む file の側にあるので、 この層は取得結果を保持するだけで
// 独自の状態を作らない。 追記した後は取り直す (= 楽観更新をしない)。 掲示板は
// 追記のみなので、 取り直しで表示が巻き戻ることがない。
//
// backend が 404 を返すのは「会議機能そのものが設定されていない」 場合で、
// 「会議が 0 件」 とは別物。 呼び出し側がタブごと隠せるように configured で返す。

const NOT_CONFIGURED = 404

export function useMeetings() {
  const [meetings, setMeetings] = useState(null) // null = 未取得
  const [configured, setConfigured] = useState(true)

  const reload = useCallback(async () => {
    try {
      const res = await apiFetch('/meetings')
      if (res.status === NOT_CONFIGURED) {
        setConfigured(false)
        setMeetings([])
        return
      }
      setConfigured(true)
      setMeetings(res.ok ? await res.json() : [])
    } catch {
      setMeetings([])
    }
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  return { meetings, configured, reload }
}

export function useMeeting(meetingId) {
  const [meeting, setMeeting] = useState(null)
  const [missing, setMissing] = useState(false)

  const reload = useCallback(async () => {
    if (!meetingId) {
      setMeeting(null)
      setMissing(false)
      return
    }
    try {
      const res = await apiFetch(`/meetings/${encodeURIComponent(meetingId)}`)
      if (!res.ok) {
        setMeeting(null)
        setMissing(true)
        return
      }
      setMissing(false)
      setMeeting(await res.json())
    } catch {
      setMeeting(null)
    }
  }, [meetingId])

  useEffect(() => {
    reload()
  }, [reload])

  return { meeting, missing, reload }
}

/** 掲示板へ 1 発言追記する。 成功したら true。 */
export async function postToBoard(meetingId, { who, kind, body }) {
  const res = await apiFetch(`/meetings/${encodeURIComponent(meetingId)}/posts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ who, kind, body }),
  })
  return res.ok
}
