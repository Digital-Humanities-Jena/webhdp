import { expect, test, type Page, type APIRequestContext } from '@playwright/test'
import { mockCurrentUser, mockSetupStatus, seedAuthToken } from './support/api'

const backend = 'http://127.0.0.1:4876'
test.skip(!process.env.WEBHDP_BROWSER_TESTING, 'Run with the isolated backend browser configuration.')

async function prepareWorkflow(page: Page, request: APIRequestContext) {
  const fixture = await (await request.post(`${backend}/__test__/workflow/fixture`)).json()
  await seedAuthToken(page, fixture.owner_token)
  await mockSetupStatus(page, true)
  await mockCurrentUser(page, { id: fixture.owner_id, email: 'workflow@example.com', role: 'admin', capabilities: [], groups: [], institutions: [], memberships: [] })
  await page.goto('/workflow/upload')
  await page.locator('#file-upload').setInputFiles({ name: 'model.glb', mimeType: 'model/gltf-binary', buffer: Buffer.from(fixture.model_base64, 'base64') })
  const uploaded = page.waitForResponse('**/api/v1/sessions/file')
  await page.getByTestId('upload-primary-action').click()
  const upload = await (await uploaded).json()
  expect(upload.success).toBe(true)
  const sessionId = upload.data.session_id
  await expect(page.getByRole('heading', { name: 'Review Files' })).toBeVisible()
  await page.getByRole('button', { name: 'Select all scanned bundles' }).click()
  await page.getByRole('button', { name: 'Continue to Metadata →' }).click()
  await page.locator('#field-title').fill('Museum model')
  await page.locator('#field-description').fill('Documented source model')
  await page.locator('#field-notes').fill('Curator has reviewed the source')
  const creator = page.locator('#field-creators-0-name')
  if (!await creator.count()) await page.getByRole('button', { name: '+ Add Creator', exact: true }).click()
  await creator.fill('Museum')
  await saveAndSelect(page)
  await expect(page.getByTestId('submit-confirm')).toBeEnabled()
  return { ...fixture, sessionId, headers: { Authorization: `Bearer ${fixture.owner_token}` } }
}

async function saveAndSelect(page: Page) {
  await page.getByRole('button', { name: 'Save & Continue →' }).click()
  await page.getByRole('button', { name: 'Continue to Pipeline →' }).click()
  await page.locator('#browser_workflow').check()
  await page.getByTestId('pipeline-continue').click()
}

async function submit(page: Page) {
  await expect(page.getByTestId('submit-confirm')).toBeEnabled()
  const response = page.waitForResponse('**/api/v2/pipelines/browser_workflow/execute')
  await page.getByTestId('submit-confirm').click()
  const accepted = await response
  expect(accepted.status()).toBe(202)
  return (await accepted.json()).data.run_id as string
}

test('real upload, metadata correction, partial results, reload, selective recovery and verified comparison', async ({ page, request }) => {
  test.setTimeout(90000)
  const fixture = await prepareWorkflow(page, request)
  const draft = (await (await request.get(`${backend}/api/v1/metadata/user/${fixture.sessionId}`, { headers: fixture.headers })).json()).data.metadata
  // Another editor saves an incomplete draft. Readiness must use the server state.
  const changed = await request.put(`${backend}/api/v1/metadata/user/${fixture.sessionId}/draft`, { headers: fixture.headers, data: { ...draft.zenodo_metadata_draft, notes: '' } })
  expect(changed.ok()).toBe(true)
  await page.getByRole('button', { name: 'Check again', exact: true }).click()
  await expect(page.getByTestId('submit-confirm')).toBeDisabled()
  const correction = page.getByTestId('submission-readiness').getByRole('link', { name: 'Review metadata', exact: true }).first()
  await expect(correction).toBeVisible()
  await correction.click()
  await page.locator('#field-notes').fill('Corrected curator review')
  await saveAndSelect(page)
  await expect(page.getByTestId('submission-readiness')).toContainText('Local checks passed for 1 selected source.')
  const first = await submit(page)
  expect((await (await request.post(`${backend}/__test__/runs/${first}/deliver`)).json()).run.status).toBe('failed')
  await expect(page.getByTestId('submission-outcomes')).toContainText('Needs attention', { timeout: 15000 })
  await page.goto(`/runs/${first}`)
  await page.reload()
  await expect(page.getByTestId('submission-outcomes')).toContainText('Prepare source: completed')
  await expect(page.getByTestId('submission-outcomes')).toContainText('Generate detail levels: failed')
  await request.post(`${backend}/__test__/runs/${first}/correct`)
  await page.getByRole('link', { name: 'Review and continue failed work' }).click()
  const retried = await submit(page)
  expect((await (await request.post(`${backend}/__test__/runs/${retried}/deliver`)).json()).run.status).toBe('completed')
  await expect(page.getByTestId('submission-outcomes')).toContainText('verified output reused', { timeout: 15000 })
  const observations = (await (await request.get(`${backend}/__test__/runs/${retried}/observations`)).json()).calls
  expect(observations.find((call: any) => call.step === 'prepare').count).toBe(1)
  expect(observations.find((call: any) => call.step === 'detail').count).toBe(2)
  const run = (await (await request.get(`${backend}/api/v2/runs/${retried}`, { headers: fixture.headers })).json()).data.run
  await page.goto(`/sessions/${fixture.sessionId}/records/${run.outcomes.records[0].record_id}`)
  await page.getByText('Compare source and geometric detail levels', { exact: true }).click()
  await page.getByRole('button', { name: 'Load comparison', exact: true }).click()
  await expect(page.getByText('The loaded files match their recorded SHA-256 checksums.')).toBeVisible()
  await expect(page.locator('model-viewer')).toHaveCount(2)
  expect((await (await request.post(`${backend}/__test__/runs/${retried}/deliver`)).json()).run.status).toBe('completed')
  expect((await (await request.get(`${backend}/__test__/runs/${retried}/observations`)).json()).calls).toEqual(observations)
})

test('lost guided submission acknowledgement reconnects after reload without a second reservation', async ({ page, request }) => {
  test.setTimeout(60000)
  const fixture = await prepareWorkflow(page, request)
  let runId = ''
  let requests = 0
  await page.route('**/api/v2/pipelines/browser_workflow/execute', async route => {
    requests++
    const accepted = await route.fetch()
    expect(accepted.status()).toBe(202)
    runId = (await accepted.json()).data.run_id
    await route.abort('failed')
  })
  await page.getByTestId('submit-confirm').click()
  await expect.poll(() => runId).not.toBe('')
  await page.reload()
  await expect(page.getByRole('button', { name: 'Cancel queued run' })).toBeVisible()
  expect(requests).toBe(1)
  await request.post(`${backend}/__test__/runs/${runId}/correct`)
  expect((await (await request.post(`${backend}/__test__/runs/${runId}/deliver`)).json()).run.status).toBe('completed')
  await expect(page.getByTestId('submission-outcomes')).toContainText('Processing completed', { timeout: 15000 })
  expect(requests).toBe(1)
  expect(fixture.sessionId).toBeGreaterThan(0)
})
