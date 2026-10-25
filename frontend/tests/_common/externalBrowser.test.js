import { describe, it, expect, vi } from 'vitest'
import { isHomeScreenWebApp, openInBrowser, safariUrl } from '../../src/_common/externalBrowser.js'

// window の代わり: 開いた窓と書き換えた行き先を覚える
function fakeWindow({ standalone = false, native = false } = {}) {
  return {
    navigator: { standalone },
    location: { href: 'https://host.example.ts.net/?ses=ses_a' },
    open: vi.fn(),
    ...(native ? { Capacitor: { isNativePlatform: () => true } } : {}),
  }
}

describe('safariUrl', () => {
  it('turns a web address into the form iOS hands to Safari', () => {
    expect(safariUrl('https://host.example.ts.net/file/open?path=%7E%2Fa.html')).toBe('x-safari-https://host.example.ts.net/file/open?path=%7E%2Fa.html')
    expect(safariUrl('HTTP://127.0.0.1:8766/x')).toBe('x-safari-http://127.0.0.1:8766/x')
  })

  it('leaves anything that is not a web address alone', () => {
    expect(safariUrl('mailto:someone@example.com')).toBeNull()
    expect(safariUrl('slack://open')).toBeNull()
  })
})

describe('isHomeScreenWebApp', () => {
  it('is the iPhone web app opened from the home screen, and not the iPhone app', () => {
    expect(isHomeScreenWebApp(fakeWindow({ standalone: true }))).toBe(true)
    expect(isHomeScreenWebApp(fakeWindow())).toBe(false)
    expect(isHomeScreenWebApp(fakeWindow({ standalone: true, native: true }))).toBe(false)
  })
})

describe('openInBrowser', () => {
  it('hands the page to Safari from the home-screen web app, and leaves the app where it was', () => {
    const win = fakeWindow({ standalone: true })
    openInBrowser('/file/open?path=%7E%2Fa.html', win)
    expect(win.location.href).toBe('x-safari-https://host.example.ts.net/file/open?path=%7E%2Fa.html')
    expect(win.open).not.toHaveBeenCalled()
  })

  it('opens a new tab elsewhere, and a new window in the iPhone app (which hands it to the default browser)', () => {
    for (const win of [fakeWindow(), fakeWindow({ standalone: true, native: true })]) {
      openInBrowser('/file/open?path=%7E%2Fa.html', win)
      expect(win.open).toHaveBeenCalledWith('https://host.example.ts.net/file/open?path=%7E%2Fa.html', '_blank', 'noreferrer')
      expect(win.location.href).toBe('https://host.example.ts.net/?ses=ses_a')
    }
  })
})
