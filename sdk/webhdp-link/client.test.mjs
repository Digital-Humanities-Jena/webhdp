import { test } from 'node:test'
import assert from 'node:assert/strict'
import { WebHdpLink, LinkError } from './client.mjs'
const baseUrl = 'http://127.0.0.1:5100/api/v1/link'
const store = () => { const values = new Map(); return { getItem: k => values.get(k), setItem: (k, v) => values.set(k, v), removeItem: k => values.delete(k) } }
test('HTTPS and API origin confinement', () => {
  assert.throws(() => new WebHdpLink({ baseUrl: 'http://example.org/link' }))
  const client = new WebHdpLink({ baseUrl, clientId: 'test' })
  assert.throws(() => client.endpoint('https://evil.example/token'))
  assert.throws(() => client.endpoint('../admin'))
  assert.throws(() => client.endpoint('/api/v1/auth'))
})
test('PKCE challenge, callback state, code exchange and memory-only token', async () => {
  let exchange; const storage = store()
  const client = new WebHdpLink({ baseUrl, clientId: 'photo', storage, fetch: async (url, options) => {
    if (url.endsWith('/discovery')) return Response.json({ issuer: baseUrl, authorization_endpoint: 'http://127.0.0.1:5173/link/authorize' })
    exchange = options; return Response.json({ access_token: 'private', expires_in: 3600, issuer: baseUrl })
  } })
  const auth = new URL(await client.authorizationUrl({ redirectUri: 'http://127.0.0.1:5191/' }))
  assert.equal(auth.searchParams.get('code_challenge_method'), 'S256')
  assert.equal(auth.searchParams.get('code_challenge').length, 43)
  await client.completeAuthorization(`http://127.0.0.1:5191/?code=once&state=${auth.searchParams.get('state')}&iss=${encodeURIComponent(baseUrl)}`)
  assert.equal(exchange.credentials, 'omit'); assert.equal(exchange.body.get('code_verifier').length, 43)
  assert.equal(client.accessToken, 'private'); assert.equal(storage.getItem(client.pendingKey), undefined)
  await assert.rejects(client.completeAuthorization('http://127.0.0.1:5191/?code=once&state=bad'))
})
test('reject mismatched callback without sending a code', async () => {
  const storage = store(); let calls = 0
  const client = new WebHdpLink({ baseUrl, clientId: 'test', storage, fetch: async () => { calls++; return Response.json({ issuer: baseUrl, authorization_endpoint: 'http://127.0.0.1:5173/link/authorize' }) } })
  const auth = new URL(await client.authorizationUrl({ redirectUri: 'http://127.0.0.1:5191/' }))
  await assert.rejects(client.completeAuthorization(`http://evil.example/?code=c&state=${auth.searchParams.get('state')}`))
  assert.equal(calls, 1)
})
test('submission retains supplied idempotency key and bearer never follows redirects', async () => {
  const client = new WebHdpLink({ baseUrl, accessToken: 'secret', fetch: async (_url, options) => {
    assert.equal(options.headers['Idempotency-Key'], 'stable'); assert.equal(options.headers.Authorization, 'Bearer secret'); assert.equal(options.redirect, 'error')
    assert.deepEqual(JSON.parse(options.body).inputs, ['upload-id']); return Response.json({ id: 'run' }, { status: 202 })
  } })
  assert.equal((await client.submit({ pipelineId: 'p', inputs: [{ id: 'upload-id' }], idempotencyKey: 'stable' })).id, 'run')
})
test('structured errors and checksum mismatch are surfaced', async () => {
  const client = new WebHdpLink({ baseUrl, accessToken: 'secret', fetch: async () => Response.json({ detail: 'Queue quota exceeded' }, { status: 429 }) })
  await assert.rejects(client.runs(), error => error instanceof LinkError && error.status === 429)
  client.fetch = async () => new Response('bad')
  await assert.rejects(client.download('r', { id: 'a', size: 3, sha256: '0'.repeat(64) }), /SHA-256/)
})
test('revocation accepts an empty RFC 7009 success and clears memory token', async () => {
  const client = new WebHdpLink({ baseUrl, accessToken: 'secret', storage: store(), fetch: async () => new Response('', { status: 200 }) })
  await client.disconnect()
  assert.equal(client.accessToken, null)
})
test('verified downloads require complete fixity metadata', async () => {
  let called = false
  const client = new WebHdpLink({ baseUrl, accessToken: 'secret', fetch: async () => { called = true; return new Response('data') } })
  await assert.rejects(client.download('r', { id: 'a', size: 4 }), /SHA-256/)
  assert.equal(called, false)
})
test('hosted handoff refuses substituted or executable URLs', () => {
  const client = new WebHdpLink({ baseUrl }); client.processingBase = 'http://127.0.0.1:5173'
  assert.equal(client.hostedUrl({ id: 'r', progress_url: 'http://127.0.0.1:5173/link/jobs/r' }), 'http://127.0.0.1:5173/link/jobs/r')
  assert.throws(() => client.hostedUrl({ id: 'r', progress_url: 'javascript:alert(1)' }))
  assert.throws(() => client.hostedUrl({ id: 'r', progress_url: 'https://elsewhere.example/link/jobs/r' }))
})
