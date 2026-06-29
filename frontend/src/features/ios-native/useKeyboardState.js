/**
 * オンスクリーンキーボードの共有状態 hook — modifier トグル / flash フィードバック /
 * touch・mouse ハンドラ / key repeat (押しっぱなしで連続入力)。
 * Adapted from clsh (https://github.com/my-claude-utils/clsh), MIT. TS → JS に移植。
 *
 * Phase J-12 (= 2026-06-29、 audit-w2-residue B sweep): 旧 useState 7 個
 * (= shiftActive / capsLock / ctrlActive / optActive / cmdActive / pressedKeys / flashingKeys)
 * を state/ui.js.keyboard singleton に統合。 setModifier / addPressedKey / removePressedKey /
 * addFlashingKey / removeFlashingKey 直呼出に置換、 ui.js export を audit-clean 化。
 */
import { useCallback, useRef, useEffect, useSyncExternalStore } from 'react'
import { keyToEscapeSequence } from '../../utils/keyboard.js'
import {
  subscribe as subscribeUi,
  getSnapshot as getUiSnapshot,
  setModifier,
  addPressedKey,
  removePressedKey,
  addFlashingKey,
  removeFlashingKey,
} from '../../state/ui.js'

const FLASH_DURATION = 150
const REPEAT_DELAY = 400      // 連続入力が始まるまでの遅延 (ms)
const REPEAT_INTERVAL = 60    // 連続入力の間隔 (ms)

const MODIFIER_IDS = new Set([
  'shift-left', 'shift-right', 'caps', 'ctrl',
  'opt-left', 'opt-right', 'cmd-left', 'cmd-right', 'fn',
])

export function useKeyboardState({ onKey }) {
  const ui = useSyncExternalStore(subscribeUi, getUiSnapshot)
  const shiftActive = ui.keyboard.shift
  const capsLock = ui.keyboard.caps
  const ctrlActive = ui.keyboard.ctrl
  const optActive = ui.keyboard.opt
  const cmdActive = ui.keyboard.cmd
  const pressedKeys = ui.keyboard.pressedKeys
  const flashingKeys = ui.keyboard.flashingKeys
  const flashTimersRef = useRef(new Map())

  const repeatDelayRef = useRef(null)
  const repeatIntervalRef = useRef(null)

  const isShifted = shiftActive || capsLock

  const stopRepeat = useCallback(() => {
    if (repeatDelayRef.current) { clearTimeout(repeatDelayRef.current); repeatDelayRef.current = null }
    if (repeatIntervalRef.current) { clearInterval(repeatIntervalRef.current); repeatIntervalRef.current = null }
  }, [])

  useEffect(() => stopRepeat, [stopRepeat])

  const flashKey = useCallback((keyId) => {
    const existing = flashTimersRef.current.get(keyId)
    if (existing) clearTimeout(existing)
    addFlashingKey(keyId)
    const timer = setTimeout(() => {
      removeFlashingKey(keyId)
      flashTimersRef.current.delete(keyId)
    }, FLASH_DURATION)
    flashTimersRef.current.set(keyId, timer)
  }, [])

  const handleKeyDown = useCallback(
    (keyDef) => {
      flashKey(keyDef.id)
      if (keyDef.id === 'shift-left' || keyDef.id === 'shift-right') { setModifier('shift', !getUiSnapshot().keyboard.shift); return }
      if (keyDef.id === 'caps') { setModifier('caps', !getUiSnapshot().keyboard.caps); return }
      if (keyDef.id === 'ctrl') { setModifier('ctrl', !getUiSnapshot().keyboard.ctrl); return }
      if (keyDef.id === 'opt-left' || keyDef.id === 'opt-right') { setModifier('opt', !getUiSnapshot().keyboard.opt); return }
      if (keyDef.id === 'cmd-left' || keyDef.id === 'cmd-right') { setModifier('cmd', !getUiSnapshot().keyboard.cmd); return }

      const seq = keyToEscapeSequence(keyDef.id, isShifted, ctrlActive)
      if (seq) onKey(seq)

      // sticky modifier は 1 打鍵でリセット (caps lock は除く)
      if (shiftActive) setModifier('shift', false)
      if (ctrlActive) setModifier('ctrl', false)
      if (optActive) setModifier('opt', false)
      if (cmdActive) setModifier('cmd', false)
    },
    [onKey, isShifted, ctrlActive, shiftActive, optActive, cmdActive, flashKey],
  )

  // 非 modifier キーの連続入力 (= base sequence を繰り返す)。
  const startRepeat = useCallback(
    (keyDef) => {
      stopRepeat()
      const seq = keyToEscapeSequence(keyDef.id, false, false)
      if (!seq) return
      repeatDelayRef.current = setTimeout(() => {
        repeatIntervalRef.current = setInterval(() => { onKey(seq) }, REPEAT_INTERVAL)
      }, REPEAT_DELAY)
    },
    [onKey, stopRepeat],
  )

  // 直近が touch だったかを記録して、 mouse イベントの重複発火を抑える。
  const isTouchRef = useRef(false)

  const handleTouchStart = useCallback(
    (keyDef) => (e) => {
      e.preventDefault()
      isTouchRef.current = true
      addPressedKey(keyDef.id)
      handleKeyDown(keyDef)
      if (!MODIFIER_IDS.has(keyDef.id)) startRepeat(keyDef)
    },
    [handleKeyDown, startRepeat],
  )

  const handleTouchEnd = useCallback(
    (keyDef) => (e) => {
      e.preventDefault()
      removePressedKey(keyDef.id)
      stopRepeat()
    },
    [stopRepeat],
  )

  const handleMouseDown = useCallback(
    (keyDef) => (e) => {
      if (isTouchRef.current) { isTouchRef.current = false; return }
      e.preventDefault()
      addPressedKey(keyDef.id)
      handleKeyDown(keyDef)
      if (!MODIFIER_IDS.has(keyDef.id)) startRepeat(keyDef)
    },
    [handleKeyDown, startRepeat],
  )

  const handleMouseUp = useCallback(
    (keyDef) => (e) => {
      e.preventDefault()
      removePressedKey(keyDef.id)
      stopRepeat()
    },
    [stopRepeat],
  )

  const isModifierActive = (id) => {
    if (id === 'shift-left' || id === 'shift-right') return isShifted
    if (id === 'caps') return capsLock
    if (id === 'ctrl') return ctrlActive
    if (id === 'opt-left' || id === 'opt-right') return optActive
    if (id === 'cmd-left' || id === 'cmd-right') return cmdActive
    return false
  }

  return {
    isShifted,
    capsLock,
    pressedKeys,
    flashingKeys,
    isModifierActive,
    handleTouchStart,
    handleTouchEnd,
    handleMouseDown,
    handleMouseUp,
  }
}
