import { expect, test, type Page } from '@playwright/test'
import { apiV1, fulfillJson, mockCurrentUser, mockSetupStatus, seedAuthToken } from './support/api'

const backend = 'http://127.0.0.1:4876'
test.skip(!process.env.WEBHDP_BROWSER_TESTING, 'Run with the isolated backend browser configuration.')

async function openPlayground(page: Page, fixture: any) {
  await seedAuthToken(page, fixture.owner_token)
  await page.route(/\/api\/v1\//, route => fulfillJson(route, { data: {} }))
  await mockSetupStatus(page, true)
  await mockCurrentUser(page, { id: fixture.owner_id, email: 'owner@example.com', role: 'user', capabilities: [], groups: [], institutions: [], memberships: [] })
  await page.route(apiV1('/tools/context'), route => fulfillJson(route, { data: { features: { native_playground: { enabled: true } } } }))
  await page.route(apiV1('/sessions'), route => fulfillJson(route, { data: { sessions: [{ id: fixture.session_id, status: 'draft', permissions: { can_edit: true } }] } }))
  await page.route(apiV1(`/sessions/${fixture.session_id}/nodes`), route => fulfillJson(route, { data: { nodes: [{ type: 'file', path: fixture.path, name: 'model.glb' }] } }))
  await page.goto('/tools/playground')
  const notice = page.getByRole('button', { name: 'OK', exact: true })
  if (await notice.isVisible()) await notice.click()
  await page.getByRole('button', { name: /Browser component.*Open/ }).click()
}

async function prepareForm(page: Page, fixture: any) {
  const dialog = page.getByRole('dialog')
  await dialog.locator('select').first().selectOption(String(fixture.session_id))
  await dialog.locator('textarea').first().fill(fixture.path)
}

test('scrolling over the Run panel reaches the form below the fold', async ({ page, request }) => {
  await page.setViewportSize({ width: 1280, height: 560 })
  const fixture = await (await request.post(`${backend}/__test__/fixture`)).json()
  await openPlayground(page, fixture)
  const dialog = page.getByRole('dialog')
  await dialog.locator('select').first().selectOption(String(fixture.session_id))
  await expect(dialog.getByText('Session Context', { exact: true })).toBeVisible()

  const inputs = dialog.getByRole('heading', { name: 'Inputs', exact: true })
  const inputsTop = () => inputs.evaluate(element => element.getBoundingClientRect().top)
  await dialog.getByRole('heading', { name: 'Run', exact: true }).hover()
  const initialInputsTop = await inputsTop()
  const initialPageTop = await page.evaluate(() => window.scrollY)

  await page.mouse.wheel(0, 1500)
  await expect.poll(inputsTop).toBeLessThan(initialInputsTop - 50)
  await expect(dialog.getByRole('button', { name: 'Run Playground' })).toBeInViewport()
  expect(await page.evaluate(() => window.scrollY)).toBe(initialPageTop)

  await dialog.getByRole('region', { name: 'Playground form and results' }).focus()
  await page.keyboard.press('Home')
  await expect.poll(inputsTop).toBeCloseTo(initialInputsTop, 0)
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('button', { name: /Browser component.*Open/ })).toBeFocused()
})

test('scrolling the narrow form reaches the stacked Run panel', async ({ page, request }) => {
  await page.setViewportSize({ width: 620, height: 560 })
  const fixture = await (await request.post(`${backend}/__test__/fixture`)).json()
  await openPlayground(page, fixture)
  const dialog = page.getByRole('dialog')
  await dialog.locator('select').first().selectOption(String(fixture.session_id))
  await expect(dialog.getByText('Session Context', { exact: true })).toBeVisible()

  const run = dialog.getByRole('button', { name: 'Run Playground' })
  const runTop = () => run.evaluate(element => element.getBoundingClientRect().top)
  await dialog.getByText('Session Context', { exact: true }).hover()
  const initialRunTop = await runTop()
  const initialPageTop = await page.evaluate(() => window.scrollY)

  await page.mouse.wheel(0, 600)
  await expect.poll(runTop).toBeLessThan(initialRunTop - 50)
  await page.mouse.wheel(0, 600)
  await expect(run).toBeInViewport()
  expect(await page.evaluate(() => window.scrollY)).toBe(initialPageTop)
})

test('real HTTP routes reject foreign sessions and out-of-scope files', async ({ request }) => {
  const fixture = await (await request.post(`${backend}/__test__/fixture`)).json()
  const payload = { component_key: 'browser_component', session_id: fixture.session_id, profile_id: 'local', inputs: { files: [fixture.path] }, async_execution: true, request_id: crypto.randomUUID() }
  const foreign = await request.post(`${backend}/api/v2/playground/execute`, { headers: { Authorization: `Bearer ${fixture.other_token}` }, data: payload })
  expect(foreign.status()).toBe(404)
  const escape = await request.post(`${backend}/api/v2/playground/execute`, { headers: { Authorization: `Bearer ${fixture.owner_token}` }, data: { ...payload, inputs: { files: ['/etc/hosts'] } } })
  expect(escape.status()).toBe(400)
})

test('lost acknowledgement reconnects after reload and delivers the persisted job once', async ({ page, request }) => {
  const fixture = await (await request.post(`${backend}/__test__/fixture`)).json()
  await openPlayground(page, fixture)
  await prepareForm(page, fixture)
  let runId = ''
  let submissions = 0
  await page.route('**/api/v2/playground/execute', async route => {
    submissions++
    const accepted = await route.fetch()
    expect(accepted.status()).toBe(202)
    runId = (await accepted.json()).data.playground_run.run_id
    await route.abort('failed')
  })
  await page.getByRole('button', { name: 'Run Playground', exact: true }).click()
  await expect.poll(() => runId).not.toBe('')
  await page.reload()
  await page.getByRole('button', { name: /Browser component.*Open/ }).click()
  await expect(page.getByRole('button', { name: 'Cancel queued run' })).toBeVisible()
  expect(submissions).toBe(1)
  const delivered = await request.post(`${backend}/__test__/runs/${runId}/deliver`)
  expect((await delivered.json()).run.status).toBe('completed')
  await page.getByRole('button', { name: 'Reconnect', exact: true }).click()
  await expect(page.getByText('Session-scoped component output', { exact: false }).first()).toBeVisible()
  expect(submissions).toBe(1)
  expect((await (await request.post(`${backend}/__test__/runs/${runId}/deliver`)).json()).run.status).toBe('completed')
})

test('queued cancellation persists and prevents late delivery from executing', async ({ page, request }) => {
  const fixture = await (await request.post(`${backend}/__test__/fixture`)).json()
  await openPlayground(page, fixture)
  await prepareForm(page, fixture)
  const accepted = page.waitForResponse('**/api/v2/playground/execute')
  await page.getByRole('button', { name: 'Run Playground', exact: true }).click()
  const runId = (await (await accepted).json()).data.playground_run.run_id
  await page.getByRole('button', { name: 'Cancel queued run' }).click()
  await expect(page.getByText('This run was cancelled before processing. Existing files and drafts were kept.', { exact: false }).first()).toBeVisible()
  const replay = await (await request.post(`${backend}/__test__/runs/${runId}/deliver`)).json()
  expect(replay.run.result.cancelled).toBe(true)
  expect(replay.run.logs).toEqual({})
})
