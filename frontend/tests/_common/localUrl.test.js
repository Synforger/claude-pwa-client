// A link written for this machine's own address, made into one the screen's device opens by the tailnet name.
import { describe, it, expect } from 'vitest'
import { onScreenHost } from '../../src/_common/localUrl.js'

const phone = { protocol: 'https:', hostname: 'mac.tail1234.ts.net' }

describe('onScreenHost', () => {
  it('puts the screen\'s scheme and host in place of localhost and 127.0.0.1, keeping the port and the path', () => {
    expect(onScreenHost('http://localhost:8776/projects/AP/pages/a.html', phone)).toBe('https://mac.tail1234.ts.net:8776/projects/AP/pages/a.html')
    expect(onScreenHost('http://127.0.0.1:8775/x?y=1#z', phone)).toBe('https://mac.tail1234.ts.net:8775/x?y=1#z')
    expect(onScreenHost('http://localhost:8776', phone)).toBe('https://mac.tail1234.ts.net:8776')
  })
  it('leaves every other URL as it is', () => {
    expect(onScreenHost('https://github.com/x', phone)).toBe('https://github.com/x')
    expect(onScreenHost('http://localhost.example.com/x', phone)).toBe('http://localhost.example.com/x')
    expect(onScreenHost('cpc-file://%2Fa', phone)).toBe('cpc-file://%2Fa')
  })
  it('leaves localhost as it is when the screen itself is opened on this machine', () => {
    expect(onScreenHost('http://localhost:8776/a', { protocol: 'http:', hostname: '127.0.0.1' })).toBe('http://localhost:8776/a')
    expect(onScreenHost('http://localhost:8776/a', null)).toBe('http://localhost:8776/a')
  })
})
