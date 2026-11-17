import test from 'node:test'
import assert from 'node:assert/strict'
import { applyPresentation, sandboxReceiptSummary } from './presentation.mjs'

const receipt = { operation: 'zenodo-sandbox-draft', environment: 'sandbox', submitted: false, publication_attempted: false, publication_status: 'unpublished_draft', deposition_id: 123, draft_url: 'https://malicious.example/', files: [{ name: 'model.glb', size: 10, sha256: 'a'.repeat(64) }] }
test('Sandbox receipt links are reconstructed from a validated identity and fixed Sandbox origin', () => {
  assert.deepEqual(sandboxReceiptSummary(receipt), { id: 123, files: 1, url: 'https://sandbox.zenodo.org/uploads/123' })
})
test('published, production, malformed and unverified receipts cannot appear as an unpublished draft', () => {
  for (const patch of [{ submitted: true }, { environment: 'production' }, { publication_attempted: true }, { publication_status: 'published' }, { deposition_id: '../evil' }, { files: [] }, { files: [{ name: 'bad.glb', size: 10, sha256: 'wrong' }] }]) assert.throws(() => sandboxReceiptSummary({ ...receipt, ...patch }))
})
test('deployment copy is inserted as literal text and absent overrides preserve original content', () => {
  const elements = { '.hero h1': { textContent: 'Original' }, '.hero p': { textContent: 'Original description' }, '.scope-note': { textContent: 'Original scope' } }
  const document = { querySelector: selector => elements[selector], getElementById: () => null }
  applyPresentation(document, { hero_title: '<script>alert(1)</script>', scope_note: 'Unpublished Sandbox only' })
  assert.equal(elements['.hero h1'].textContent, '<script>alert(1)</script>')
  assert.equal(elements['.hero p'].textContent, 'Original description')
  assert.equal(elements['.scope-note'].textContent, 'Unpublished Sandbox only')
})
