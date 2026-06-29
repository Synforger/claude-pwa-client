import { useRef, useEffect, useCallback, useSyncExternalStore } from 'react'
import { SUPPORTED_IMAGE_TYPES } from '../../constants.js'
import { putImage } from './imageStore.js'
import {
  subscribe as subscribeEphemeral,
  getSnapshot as getEphemeralSnapshot,
  setAttachments as storeSetAttachments,
} from '../../state/ephemeral.js'

// セッション (session_id) ごとの添付ファイル状態。 dict は lazy 拡張する。
//
// Phase J-11 (= 2026-06-29、 audit-w2-residue 第 1 弾): J-9 と同型の状態二重管理を解消。
// 旧 useState({}) (= ChatPanel 内のみ生きる local state) → state/ephemeral.js singleton 直結。
// store の setAttachments(sid, items) は single-sid のみ更新するので、 mutation 関数側で
// 該当 sid の最新 items を計算して直呼出する。 ChatPanel 経由の戻り値 shape は不変。
export function useAttachments(activeSession) {
  const ephem = useSyncExternalStore(subscribeEphemeral, getEphemeralSnapshot)
  const attachments = ephem.attachments
  const fileInputRef = useRef(null)
  const attachmentsRef = useRef(attachments)

  useEffect(() => { attachmentsRef.current = attachments }, [attachments])

  // アンマウント時に未送信 BlobURL を解放 (全セッション分)。 store 自体は維持 (= 他 mount
  // instance がいる可能性あり)、 BlobURL の release のみ実施。
  useEffect(() => {
    return () => {
      const dict = attachmentsRef.current
      for (const sid of Object.keys(dict)) {
        for (const item of dict[sid] || []) {
          if (item.url) URL.revokeObjectURL(item.url)
        }
      }
    }
  }, [])

  // 画像は IndexedDB に永続化して imageId を attachment item に持たせる。 送信後の
  // user bubble に imageRefs として保存しておくと、 ObjectURL が失効するアプリ再起動
  // / リロード後でも IndexedDB から取り直して表示できる (= 旧 chat UI で「画像が ?
  // 表示になる」 現象の根治)。 非画像 (= テキストファイル) は IndexedDB に入れない。
  const handleFileSelect = async (e) => {
    const sid = activeSession?.id
    if (!sid) return
    const files = Array.from(e.target.files || [])
    e.target.value = ''
    // F-31: putImage は IndexedDB の readwrite tx + _enforceCaps を内部で叩くので、
    // Promise.all で並列に走らせると tx が重なって lock 待ちが発生し、 cap 計算も
    // race する。 直列ループにすれば tx は順に commit され、 cap 評価も常に直前の
    // commit 反映済みで安定する。 画像数は通常 1-5 程度なので直列化のレイテンシ
    // 増は実用上無視可能。
    const newItems = []
    for (const file of files) {
      const isImage = SUPPORTED_IMAGE_TYPES.includes(file.type)
      let imageId = null
      if (isImage) {
        try { imageId = await putImage(file) } catch { /* 失敗時は imageRefs 無しで送る */ }
      }
      newItems.push({
        file,
        url: isImage ? URL.createObjectURL(file) : null,
        imageId,
      })
    }
    const cur = getEphemeralSnapshot().attachments[sid] || []
    storeSetAttachments(sid, [...cur, ...newItems])
  }

  const removeAttachment = (sid, index) => {
    const cur = [...(getEphemeralSnapshot().attachments[sid] || [])]
    const removed = cur.splice(index, 1)
    if (removed[0]?.url) URL.revokeObjectURL(removed[0].url)
    storeSetAttachments(sid, cur)
  }

  const clearAttachments = useCallback((sid) => {
    storeSetAttachments(sid, [])
  }, [])

  return {
    attachments,
    fileInputRef,
    handleFileSelect,
    removeAttachment,
    clearAttachments,
  }
}
