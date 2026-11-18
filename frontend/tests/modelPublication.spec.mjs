import { describe, expect, it } from 'vitest'
import { sandboxDraftPreviewUrl } from '@/services/modelPublication.service'

const preview = 'https://sandbox.zenodo.org/records/482?preview=1&token=header123.payload_-.signature'

describe('Sandbox draft preview link', () => {
  it('accepts a record-scoped preview on the Sandbox origin', () => {
    expect(sandboxDraftPreviewUrl(preview, 482)).toBe(preview)
  })

  it.each([
    [preview, 481],
    [preview.replace('sandbox.zenodo.org', 'sandbox.zenodo.org.example.com'), 482],
    [preview.replace('sandbox.zenodo.org', 'sandbox.zenodo.org@other.example'), 482],
    [preview.replace('sandbox.zenodo.org', 'sandbox.zenodo.org:444'), 482],
    [preview.replace('https://', 'http://'), 482],
    [preview.replace('preview=1&', ''), 482],
    [preview + '&redirect_to=https://example.com', 482],
    [preview + '\n', 482],
    [preview + 'a'.repeat(2000), 482],
  ])('rejects invalid preview %s', (url, id) => {
    expect(sandboxDraftPreviewUrl(url, id)).toBe('')
  })
})
