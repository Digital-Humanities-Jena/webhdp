/** WebHDP-Link v1 browser/Node client. No framework, cookies, or HPC credentials. */
export const DEFAULT_SCOPE = 'pipelines:read uploads:write runs:write runs:read artifacts:read'
export class LinkError extends Error {
  constructor(problem, status) {
    super(problem.detail || problem.error_description || problem.title || 'WebHDP-Link request failed')
    this.name = 'LinkError'; this.status = status; this.problem = problem
  }
}
function safeBase(value) {
  const url = new URL(value)
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback)) throw new Error('Use HTTPS for WebHDP-Link; HTTP is allowed only on loopback.')
  if (url.username || url.password || url.search || url.hash) throw new Error('Invalid WebHDP-Link base URL')
  return url.href.replace(/\/$/, '')
}
const base64url = bytes => btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
const nonce = () => base64url(crypto.getRandomValues(new Uint8Array(32)))
export class WebHdpLink {
  constructor({ baseUrl, clientId, accessToken = null, fetch: fetchFn = globalThis.fetch, storage = globalThis.sessionStorage }) {
    this.baseUrl = safeBase(baseUrl); this.clientId = clientId
    this.accessToken = accessToken; this.fetch = fetchFn.bind(globalThis); this.storage = storage
    this.pendingKey = `webhdp-link:oauth:${this.baseUrl}:${clientId}`
  }
  endpoint(path) {
    const url = new URL(path, `${this.baseUrl}/`)
    if (url.origin !== new URL(this.baseUrl).origin || !url.pathname.startsWith(`${new URL(this.baseUrl).pathname}/`)) throw new Error('Refusing a URL outside this WebHDP-Link API')
    return url.href
  }
  async request(path, { method = 'GET', body, headers = {}, auth = true, signal, raw = false } = {}) {
    if (auth && !this.accessToken) throw new Error('Connect to WebHDP first.')
    const options = { method, headers: { Accept: 'application/json', ...headers }, credentials: 'omit', redirect: 'error', signal }
    if (auth) options.headers.Authorization = `Bearer ${this.accessToken}`
    if (body !== undefined) {
      if (body instanceof FormData || body instanceof URLSearchParams) options.body = body
      else { options.body = JSON.stringify(body); options.headers['Content-Type'] = 'application/json' }
    }
    const response = await this.fetch(this.endpoint(path), options)
    if (!response.ok) {
      let problem = { title: response.statusText }
      try { problem = await response.json() } catch { /* transport error */ }
      if (response.status === 401 && auth) this.accessToken = null
      throw new LinkError(problem, response.status)
    }
    if (raw) return response
    if (response.status === 204) return null
    const text = await response.text()
    return text ? JSON.parse(text) : null
  }
  discovery() { return this.request('discovery', { auth: false }) }
  async authorizationUrl({ redirectUri, scope = DEFAULT_SCOPE }) {
    const discovery = await this.discovery()
    if (discovery.issuer !== this.baseUrl) throw new Error('Discovery issuer does not match the configured WebHDP instance')
    const verifier = nonce(), state = nonce()
    const challenge = base64url(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))))
    const authorization = new URL(discovery.authorization_endpoint)
    safeBase(`${authorization.origin}${authorization.pathname}`)
    if (!authorization.pathname.endsWith('/link/authorize')) throw new Error('Invalid hosted authorization endpoint')
    const processingBase = `${authorization.origin}${authorization.pathname.slice(0, -'/link/authorize'.length)}`
    const pending = { verifier, state, redirectUri, issuer: discovery.issuer, processingBase, created: Date.now() }
    this.storage.setItem(this.pendingKey, JSON.stringify(pending))
    authorization.search = new URLSearchParams({ response_type: 'code', client_id: this.clientId, redirect_uri: redirectUri, scope, state, code_challenge: challenge, code_challenge_method: 'S256' }).toString()
    return authorization.href
  }
  async completeAuthorization(callbackUrl = globalThis.location.href) {
    const url = new URL(callbackUrl)
    if (!url.searchParams.has('code') && !url.searchParams.has('error')) return false
    let pending
    try { pending = JSON.parse(this.storage.getItem(this.pendingKey)) } catch { /* invalid state */ }
    this.storage.removeItem(this.pendingKey)
    const callbackBase = new URL(url)
    for (const key of ['code', 'state', 'error', 'error_description', 'iss']) callbackBase.searchParams.delete(key)
    if (!pending || url.searchParams.get('state') !== pending.state || Date.now() - pending.created > 600000 || Date.now() < pending.created || callbackBase.href !== pending.redirectUri) throw new Error('Authorization response does not match this browser request. Connect again.')
    if (globalThis.history && globalThis.location?.origin === url.origin) globalThis.history.replaceState({}, '', callbackBase.href)
    if (url.searchParams.has('error')) throw new LinkError({ title: url.searchParams.get('error'), detail: url.searchParams.get('error_description') || 'Connection was declined.' }, 403)
    if (url.searchParams.get('iss') !== pending.issuer) throw new Error('Authorization issuer mismatch')
    const token = await this.request('oauth/token', { auth: false, method: 'POST', body: new URLSearchParams({ grant_type: 'authorization_code', code: url.searchParams.get('code'), client_id: this.clientId, redirect_uri: pending.redirectUri, code_verifier: pending.verifier }) })
    if (token.issuer !== pending.issuer) throw new Error('Token issuer mismatch')
    this.accessToken = token.access_token
    this.processingBase = pending.processingBase
    this.expiresAt = Date.now() + token.expires_in * 1000
    return true
  }
  hostedUrl(run) {
    if (!this.processingBase || !run.progress_url || !run.id) throw new Error('The hosted job URL is unavailable')
    const expected = `${this.processingBase}/link/jobs/${encodeURIComponent(run.id)}`
    if (run.progress_url !== expected) throw new Error('The hosted job URL does not match the authorized WebHDP instance')
    return expected
  }
  async disconnect() {
    if (this.accessToken) await this.request('oauth/revoke', { auth: false, method: 'POST', body: new URLSearchParams({ token: this.accessToken }) })
    this.accessToken = null
    this.storage?.removeItem(this.pendingKey)
  }
  pipelines() { return this.request('pipelines') }
  pipeline(id) { return this.request(`pipelines/${encodeURIComponent(id)}`) }
  upload(file, { signal } = {}) { const body = new FormData(); body.append('file', file, file.name); return this.request('uploads', { method: 'POST', body, signal }) }
  submit({ pipelineId, inputs, parameters = {}, idempotencyKey = crypto.randomUUID() }) {
    return this.request('runs', { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey }, body: { pipeline_id: pipelineId, inputs: inputs.map(input => typeof input === 'string' ? input : input.id), parameters } })
  }
  async process({ pipelineId, files, parameters = {}, idempotencyKey = crypto.randomUUID(), onUpload = () => {} }) {
    const inputs = []
    for (const file of files) { const input = await this.upload(file); inputs.push(input); onUpload(input, inputs.length, files.length) }
    return this.submit({ pipelineId, inputs, parameters, idempotencyKey })
  }
  deleteUpload(id) { return this.request(`uploads/${encodeURIComponent(id)}`, { method: 'DELETE' }) }
  runs() { return this.request('runs') }
  run(id, options) { return this.request(`runs/${encodeURIComponent(id)}`, options) }
  cancel(id) { return this.request(`runs/${encodeURIComponent(id)}/cancel`, { method: 'POST', body: {} }) }
  async wait(id, { onProgress = () => {}, interval = 1000, timeout = 3600000, signal } = {}) {
    const start = Date.now()
    while (true) {
      if (signal?.aborted) throw signal.reason || new Error('Polling stopped')
      const run = await this.run(id, { signal }); onProgress(run)
      if (['succeeded', 'failed', 'cancelled'].includes(run.status)) return run
      if (Date.now() - start >= timeout) throw new Error('Polling timed out; the job remains available in WebHDP.')
      await new Promise((resolve, reject) => {
        const abort = () => { clearTimeout(timer); reject(signal.reason || new Error('Polling stopped')) }
        const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve() }, interval)
        signal?.addEventListener('abort', abort, { once: true })
      })
    }
  }
  async download(runId, artifact) {
    if (!Number.isSafeInteger(artifact.size) || artifact.size < 0 || !/^[a-f0-9]{64}$/.test(artifact.sha256 || '')) throw new Error('Artifact size and SHA-256 are required for verified download')
    const response = await this.request(`runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifact.id)}`, { raw: true })
    const buffer = await response.arrayBuffer()
    if (artifact.size !== undefined && buffer.byteLength !== artifact.size) throw new Error('Downloaded artifact size mismatch')
    if (artifact.sha256) {
      const actual = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))).map(v => v.toString(16).padStart(2, '0')).join('')
      if (actual !== artifact.sha256) throw new Error('Downloaded artifact SHA-256 mismatch')
    }
    return new Blob([buffer], { type: artifact.media_type || 'application/octet-stream' })
  }
}
