import { describe, it, expect, vi, beforeEach } from 'vitest'

// Edit 行は「編集後の本文がファイルのどこに居るか」 を出すために /file を引く。 1 つのファイルを
// 複数回編集したターンでは Edit 行の数だけ基準行キャッシュのキーが分かれるため、 旧実装は
// **同じファイルを Edit 行の数だけ取りに行っていた** (= 2026-08-03 実測: 同一秒に同一ファイル
// 7 重複、 全体で 314 リクエスト中ユニーク 70)。 さらに各行が自分の AbortSignal 付きで取るので、
// タブを素早く切り替えると abort → 未キャッシュ → 次の表示でまた全件取得を繰り返していた。
//
// module レベルのキャッシュを持つので、 test ごとに resetModules して素の状態から始める。

const FILE_BODY = 'line1\nline2\nTARGET\nline4\n'

function mockApi() {
  const calls = []
  vi.doMock('../../utils/api.js', () => ({
    apiFetch: vi.fn((url) => {
      calls.push(url)
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ content: FILE_BODY }),
      })
    }),
  }))
  return calls
}

async function loadSubject() {
  const mod = await import('./MessageItem.jsx')
  return mod.fetchEditBaseLine
}

describe('fetchEditBaseLine — ファイル取得の重複排除', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.doUnmock('../../utils/api.js')
  })

  it('同じファイルへの同時要求はまとめて 1 回しか取りに行かない', async () => {
    const calls = mockApi()
    const fetchEditBaseLine = await loadSubject()
    const results = await Promise.all([
      fetchEditBaseLine('/a.ts', 'TARGET'),
      fetchEditBaseLine('/a.ts', 'line2'),
      fetchEditBaseLine('/a.ts', 'line4'),
    ])
    expect(calls).toHaveLength(1)
    expect(results).toEqual([3, 2, 4])
  })

  it('取得済みファイルへの後続要求は再取得しない', async () => {
    const calls = mockApi()
    const fetchEditBaseLine = await loadSubject()
    await fetchEditBaseLine('/a.ts', 'TARGET')
    await fetchEditBaseLine('/a.ts', 'line2')
    expect(calls).toHaveLength(1)
  })

  it('別ファイルはそれぞれ 1 回ずつ取る', async () => {
    const calls = mockApi()
    const fetchEditBaseLine = await loadSubject()
    await Promise.all([
      fetchEditBaseLine('/a.ts', 'TARGET'),
      fetchEditBaseLine('/b.ts', 'TARGET'),
    ])
    expect(calls).toHaveLength(2)
  })

  it('呼び出し側が abort しても取得は完走し、 次の要求は再取得しない', async () => {
    const calls = mockApi()
    const fetchEditBaseLine = await loadSubject()
    const ctrl = new AbortController()
    const p = fetchEditBaseLine('/a.ts', 'TARGET', ctrl.signal)
    ctrl.abort()
    expect(await p).toBe(null)          // 捨てた呼び出しには結果を返さない
    expect(await fetchEditBaseLine('/a.ts', 'TARGET')).toBe(3)
    expect(calls).toHaveLength(1)       // ← 旧実装はここで 2 回目を取りに行っていた
  })

  it('見つからない本文は null を確定値としてキャッシュする (= 再取得しない)', async () => {
    const calls = mockApi()
    const fetchEditBaseLine = await loadSubject()
    expect(await fetchEditBaseLine('/a.ts', 'MISSING')).toBe(null)
    expect(await fetchEditBaseLine('/a.ts', 'MISSING')).toBe(null)
    expect(calls).toHaveLength(1)
  })

  it('引数が欠けていれば取得しない', async () => {
    const calls = mockApi()
    const fetchEditBaseLine = await loadSubject()
    expect(await fetchEditBaseLine('', 'TARGET')).toBe(null)
    expect(await fetchEditBaseLine('/a.ts', '')).toBe(null)
    expect(calls).toHaveLength(0)
  })
})
