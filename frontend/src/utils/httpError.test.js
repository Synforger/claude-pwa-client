// translateHttpErrorDetail (= backend error detail → 表示文字列) の契約 test。
import { describe, it, expect } from 'vitest'
import { translateHttpErrorDetail } from './httpError.js'

describe('translateHttpErrorDetail', () => {
  it('旧仕様の plain string はそのまま返す', () => {
    expect(translateHttpErrorDetail('boom')).toBe('boom')
  })

  it('null / undefined は fallback', () => {
    expect(translateHttpErrorDetail(null, 'FB')).toBe('FB')
    expect(translateHttpErrorDetail(undefined)).toBe('')
  })

  it('object でも string でもない型は fallback', () => {
    expect(translateHttpErrorDetail(42, 'FB')).toBe('FB')
  })

  it('未知 code は message フォールバックに倒れる', () => {
    expect(translateHttpErrorDetail({ code: 'no_such_code_xyz', message: 'raw msg' })).toBe('raw msg')
  })

  it('code も message も無い object は fallback', () => {
    expect(translateHttpErrorDetail({}, 'FB')).toBe('FB')
  })
})
