import { afterEach, describe, expect, it, vi } from 'vitest'
import { Blob as NodeBlob } from 'node:buffer'
import { createHash, webcrypto } from 'node:crypto'
import { authorizationParameters, linkLoginDestination, navigateLinkCallback, verifyLinkArtifact, isEmbeddedLinkWindow } from '../src/utils/webhdpLink'
describe('WebHDP-Link redirect boundaries', () => {
  it('preserves local consent requests and rejects external redirects', () => {
    expect(linkLoginDestination('/link/jobs')).toBe('/link/jobs')
    expect(linkLoginDestination('/account/setup')).toBe('/account/setup')
    expect(linkLoginDestination('/link/jobs/run-123')).toBe('/link/jobs/run-123')
    expect(linkLoginDestination('/link/jobs/run-123/artifacts')).toBe('/workflow/upload')
    expect(linkLoginDestination('/link/authorize?client_id=piano&state=abc')).toBe('/link/authorize?client_id=piano&state=abc')
    for (const target of ['https://evil.example/link/authorize?client_id=a', '//evil.example/link/authorize?client_id=a', '/\\evil.example/link/authorize?client_id=a', '/dashboard', ['/link/authorize?client_id=a'], '/link/authorize?client_id=a\n']) expect(linkLoginDestination(target)).toBe('/workflow/upload')
  })
  it('ignores extra fields and makes duplicate OAuth query values invalid', () => {
    const result = authorizationParameters({ client_id: ['one', 'two'], state: 'opaque', injected: 'ignored' }); expect(result.client_id).toBe(''); expect(result.state).toBe('opaque'); expect(result).not.toHaveProperty('injected')
  })
  it('rejects responses outside the registered redirect before navigation', () => {
    for (const target of ['https://evil.example/callback?code=a', 'https://good.example/other?code=a', 'javascript:alert(1)', 'https://user:secret@good.example/callback', 'https://good.example/callback#code=a']) expect(() => navigateLinkCallback(target, 'https://good.example/callback')).toThrow()
    expect(() => navigateLinkCallback('https://good.example/callback?tenant=b&code=a', 'https://good.example/callback?tenant=a')).toThrow()
  })
})

describe('WebHDP-Link output verification', () => {
  afterEach(() => vi.unstubAllGlobals())
  const artifact = { size: 4, sha256: createHash('sha256').update('midi').digest('hex') }
  it('accepts matching output bytes', async () => {
    vi.stubGlobal('crypto', webcrypto)
    await expect(verifyLinkArtifact(new NodeBlob(['midi']), artifact)).resolves.toBeUndefined()
  })
  it('rejects truncated bytes before hashing', async () => {
    vi.stubGlobal('crypto', webcrypto)
    await expect(verifyLinkArtifact(new NodeBlob(['mid']), artifact)).rejects.toThrow('size does not match')
  })
  it('rejects mismatched hashes and missing secure verification', async () => {
    vi.stubGlobal('crypto', webcrypto)
    await expect(verifyLinkArtifact(new NodeBlob(['evil']), artifact)).rejects.toThrow('checksum does not match')
    await expect(verifyLinkArtifact(new NodeBlob(['midi']), { size: 4, sha256: 'invalid' })).rejects.toThrow('no valid checksum')
    vi.stubGlobal('crypto', {})
    await expect(verifyLinkArtifact(new NodeBlob(['midi']), artifact)).rejects.toThrow('cannot verify')
  })
})

it('recognizes embedded consent and denies an inaccessible browsing context', () => {
  const top = {}
  expect(isEmbeddedLinkWindow({ self: top, top })).toBe(false)
  expect(isEmbeddedLinkWindow({ self: {}, top })).toBe(true)
  expect(isEmbeddedLinkWindow({ get top() { throw new Error('blocked') } })).toBe(true)
})
