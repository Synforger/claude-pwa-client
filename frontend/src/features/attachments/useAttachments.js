import { useRef, useCallback, useSyncExternalStore } from 'react'
import { SUPPORTED_IMAGE_TYPES } from '../../_common/constants.js'
import { putImage, peekImageURL, deleteImage } from './imageStore.js'
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

  // An image is saved in IndexedDB (imageStore) and its item carries the imageId and the URL the store keeps for it:
  // the bar here and the bubble sent from it show the same URL, which the store revokes when it deletes the image.
  // The bubble keeps the imageId in imageRefs, so after a reload the image is read back from IndexedDB. A file that
  // is not an image (text) is not saved there.
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
        try { imageId = await putImage(file) } catch { /* sent without imageRefs, and shown without a preview */ }
      }
      newItems.push({
        file,
        url: imageId ? peekImageURL(imageId) : null,
        imageId,
      })
    }
    const cur = getEphemeralSnapshot().attachments[sid] || []
    storeSetAttachments(sid, [...cur, ...newItems])
  }

  const removeAttachment = (sid, index) => {
    const cur = [...(getEphemeralSnapshot().attachments[sid] || [])]
    const removed = cur.splice(index, 1)
    // An image taken back before it was sent has no bubble: it and its URL go now.
    if (removed[0]?.imageId) deleteImage(removed[0].imageId).catch(() => {})
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
