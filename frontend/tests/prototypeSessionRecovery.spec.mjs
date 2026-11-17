import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { LinkError } from '../../sdk/webhdp-link/client.mjs'
import { linkProgressPhase } from '../../examples/webhdp-link/shared/presentation.mjs'
import { linkProgressPhase as hostedProgressPhase } from '../src/utils/webhdpLink'

const root = resolve(process.cwd(), '../examples/webhdp-link')
const html = await readFile(resolve(root, 'model-depot/index.html'), 'utf8')
const source = await readFile(resolve(root, 'shared/app.mjs'), 'utf8')
// Execute the actual static module in jsdom, injecting only its two imports and
// network/navigation boundaries. This keeps the tested event handlers unchanged.
const boot = new (Object.getPrototypeOf(async function () {}).constructor)(
  'WebHdpLink', 'applyPresentation', 'renderSandboxReceipt', 'linkProgressPhase', 'fetch', 'document', 'window', 'location',
  source.replace(/^import .*\n/gm, ''),
)
const run = { id: 'accepted-job-123', pipeline_id: 'test-pipeline', status: 'running', progress: { completed: 0, total: 1 }, artifacts: [] }

async function start(wait) {
  document.body.innerHTML = html.match(/<body[^>]*>([\s\S]*)<\/body>/)[1]
  document.body.dataset.app = 'model-depot'
  let client
  class Client {
    constructor() { client = this; this.accessToken = 'current-browser-token' }
    completeAuthorization = vi.fn(async () => true)
    pipeline = vi.fn(async () => ({ name: 'Test pipeline', input: { extensions: ['.obj'] }, parameter_schema: { properties: {} } }))
    runs = vi.fn(async () => ({ runs: [run] }))
    wait = vi.fn(wait)
    disconnect = vi.fn(async () => { throw new Error('Expiry must not revoke an accepted job grant') })
    authorizationUrl = vi.fn(async () => 'http://webhdp.test/link/authorize?state=new-state')
  }
  const location = { origin: 'http://model.test', assign: vi.fn() }
  const pageWindow = { addEventListener: vi.fn() }
  await boot(Client, vi.fn(), vi.fn(), linkProgressPhase, async () => ({ ok: true, json: async () => ({ base_url: 'http://webhdp.test/api/v1/link', client_id: 'model', pipeline_id: 'test-pipeline', poll_interval_ms: 6000 }) }), document, pageWindow, location)
  return { client, location }
}

afterEach(() => { document.body.replaceChildren() })

describe('prototype connection recovery', () => {
  it('expires locally without revocation and reconnects to the same accepted job through history', async () => {
    const first = await start(async () => { throw new LinkError({ title: 'Expired token' }, 401) })
    document.querySelector('#recent-list button').click(); await flushPromises()
    expect(first.client.wait.mock.calls[0][1].interval).toBe(6000)
    expect(first.client.accessToken).toBeNull()
    expect(first.client.disconnect).not.toHaveBeenCalled()
    expect(document.querySelector('#connect').textContent).toBe('Connect with WebHDP')
    expect(document.querySelector('#run').disabled).toBe(true)
    expect(document.querySelector('#cancel').disabled).toBe(true)
    expect(document.querySelector('#message').textContent).toContain('Accepted jobs continue processing')
    await document.querySelector('#connect').onclick(); await flushPromises()
    expect(first.location.assign).toHaveBeenCalledWith('http://webhdp.test/link/authorize?state=new-state')
    expect(first.client.disconnect).not.toHaveBeenCalled()

    const completed = { ...run, status: 'succeeded', progress: { completed: 1, total: 1 } }
    const second = await start(async (_id, { onProgress }) => { onProgress(completed); return completed })
    document.querySelector('#recent-list button').click(); await flushPromises()
    expect(second.client.wait).toHaveBeenCalledWith(run.id, expect.any(Object))
    expect(document.querySelector('#status').dataset.state).toBe('succeeded')
    expect(document.querySelector('#message').textContent).toContain('Processing complete')
    expect(second.client.disconnect).not.toHaveBeenCalled()
  })

  it('keeps the browser connection for non-authentication processing failures', async () => {
    const { client } = await start(async () => { throw new LinkError({ detail: 'Temporary service failure' }, 503) })
    document.querySelector('#recent-list button').click(); await flushPromises()
    expect(document.querySelector('#message').textContent).toBe('Temporary service failure')
    expect(client.accessToken).toBe('current-browser-token')
    expect(document.querySelector('#connect').textContent).toBe('Disconnect')
    expect(client.disconnect).not.toHaveBeenCalled()
  })
})

describe('processing phase presentation', () => {
  it('shows resource waiting separately from stable running status and follows phase transitions', async () => {
    let progress, finish
    await start((_id, options) => { progress = options.onProgress; return new Promise(resolve => { finish = resolve }) })
    document.querySelector('#recent-list button').click(); await flushPromises()
    progress({ ...run, progress: { completed: 0, total: 1, phase: 'waiting_for_resources', node: 'private-node' } })
    expect(document.querySelector('#status').dataset.state).toBe('running')
    expect(document.querySelector('#run-meta [role="status"]').textContent).toContain('Waiting for resources')
    expect(document.querySelector('#run-meta').textContent).toContain('Processing will start when they are available')
    expect(document.body.textContent).not.toContain('private-node')
    progress({ ...run, progress: { completed: 0, total: 1, phase: 'processing' } })
    expect(document.querySelector('#run-meta strong').textContent).toBe('Processing')
    progress({ ...run, progress: { completed: 1, total: 1, phase: 'finalizing' } })
    expect(document.querySelector('#run-meta strong').textContent).toBe('Preparing results')
    const failed = { ...run, status: 'failed', progress: { completed: 1, total: 1, phase: 'completed' } }
    progress(failed); finish(failed); await flushPromises()
    expect(document.querySelector('#status').dataset.state).toBe('failed')
    expect(document.querySelector('#run-meta [role="status"]')).toBeNull()
  })

  it('keeps unknown phases neutral and hosted/prototype labels consistent', () => {
    expect(linkProgressPhase(run).label).toBe('Job in progress')
    for (const phase of ['<private-command>', '__proto__', 'constructor']) expect(linkProgressPhase({ ...run, progress: { phase } }).label).toBe('Job in progress')
    for (const status of ['queued', 'running', 'succeeded', 'failed', 'cancelled']) {
      for (const phase of [undefined, 'queued', 'waiting_for_resources', 'processing', 'finalizing', 'completed']) {
        const value = { status, progress: { phase } }
        expect(linkProgressPhase(value)).toEqual(hostedProgressPhase(value))
        if (['succeeded', 'failed', 'cancelled'].includes(status)) expect(linkProgressPhase(value)).toBeNull()
      }
    }
  })
})
