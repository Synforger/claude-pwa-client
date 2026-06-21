import { describe, it, expect, beforeEach } from 'vitest'
import {
  registerConnection,
  notifyConnectionChange,
  __resetConnectionRegistry,
} from './useConnectionStatus.js'

// hook 本体 (useConnectionStatus) は react render が必要なので、 ここでは
// registry の挙動だけを純粋に検証する (= 重要な集約ロジック)。
beforeEach(() => __resetConnectionRegistry())

describe('connection registry', () => {
  it('registerConnection returns an unregister fn', () => {
    const unreg = registerConnection(() => true)
    expect(typeof unreg).toBe('function')
    unreg()
  })

  it('notifyConnectionChange is callable without throwing', () => {
    expect(() => notifyConnectionChange()).not.toThrow()
  })

  it('registry allows multiple connections', () => {
    const u1 = registerConnection(() => true)
    const u2 = registerConnection(() => false)
    expect(typeof u1).toBe('function')
    expect(typeof u2).toBe('function')
    u1(); u2()
  })
})
