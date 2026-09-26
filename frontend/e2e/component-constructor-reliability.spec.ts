import { expect, test, type Page } from '@playwright/test'
import { adminUser, apiV1, apiV2, fulfillJson, loginThroughUi, mockCurrentUser, mockLogin, mockSetupStatus } from './support/api'

async function shell(page: Page) {
  await page.route(/\/api\/v[12]\//, route => fulfillJson(route, { success: true, data: {} }))
  await mockSetupStatus(page, true)
  await mockLogin(page, { user: adminUser })
  await mockCurrentUser(page, adminUser)
  await page.route(apiV1('/tools/context'), route => fulfillJson(route, { data: { features: {
    pipeline_constructor: { enabled: true }, native_playground: { enabled: true }, hdp_component_installer: { enabled: true },
  } } }))
  await loginThroughUi(page, { email: adminUser.email })
  const notice = page.getByRole('button', { name: 'OK', exact: true })
  if (await notice.isVisible()) await notice.click()
}
const config = { identifier: 'image_review', name: 'Image review', version: '1.0.0', steps: [
  { id: 'inspect', name: 'Inspect image', component_ref: 'image_metadata_extractor', execution_profile_ref: 'builtin_default', scope: 'record' },
] }
const component = {
  key: 'image_metadata_extractor', name: 'Image metadata', version: '1.0.0',
  constructor_schema: { title: 'Image metadata', metadata: { category: 'Images', tags: [] }, inputs: [], outputs: [], profiles: [{ id: 'builtin_default' }] },
  playground_schema: { inputs: [], outputs: [], parameter_groups: [], metadata: { category: 'Images' } },
}

for (const width of [375, 1536]) {
  test(`constructor keeps checks tied to edits at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    await shell(page)
    await page.route(apiV2('/pipelines'), route => fulfillJson(route, { data: { pipelines: [config] } }))
    await page.route(apiV2('/pipelines/image_review'), route => fulfillJson(route, { data: { pipeline: { config } } }))
    await page.route(apiV2('/components'), route => fulfillJson(route, { data: { components: [component] } }))
    await page.route(apiV2('/pipelines/validate'), route => fulfillJson(route, { data: { valid: true, errors: [], warnings: [] } }))
    await page.goto('/tools/pipeline-constructor')
    await page.getByTestId('validate-pipeline').click()
    await expect(page.getByText('Passed', { exact: true })).toBeVisible()
    await page.getByRole('textbox', { name: 'Name', exact: true }).fill('Changed image review')
    await expect(page.getByText('Unpublished changes', { exact: true })).toBeVisible()
    await expect(page.getByText('Not checked for current edits', { exact: true })).toBeVisible()
    await expect(page.getByTestId('run-pipeline-execution')).toBeDisabled()
    page.once('dialog', dialog => dialog.dismiss())
    await page.getByRole('button', { name: 'New Pipeline', exact: true }).click()
    await expect(page.getByRole('textbox', { name: 'Name', exact: true })).toHaveValue('Changed image review')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('constructor.png'), fullPage: true })
  })
}

test('installer clears validation after source edits and explains failed checks', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 375, height: 1000 })
  await shell(page)
  await page.route(apiV1('/tools/hdp-components/catalog'), route => fulfillJson(route, { data: { components: [{
    component_key: 'image_metadata_extractor', label: 'Image metadata', version: '1.0.0', manifest_text: 'metadata: {name: image_metadata_extractor}',
    sif_source: '/work/components/image.sif', catalog_source: 'local',
  }] } }))
  let ready = true
  await page.route(apiV1('/tools/hdp-components/validate'), route => fulfillJson(route, { data: { checks: {
    manifest_schema: { success: true }, hpc_link: { success: ready, ...(ready ? {} : { error: 'Compute service is unavailable' }) },
  } } }))
  await page.goto('/tools/hdp-components/install')
  await page.getByRole('button', { name: 'Validate Package', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Install on HPC', exact: true })).toBeEnabled()
  await page.getByRole('textbox', { name: 'SIF Source', exact: true }).fill('/work/components/other.sif')
  await expect(page.getByRole('button', { name: 'Install on HPC', exact: true })).toBeDisabled()
  ready = false
  await page.getByRole('button', { name: 'Validate Package', exact: true }).click()
  await expect(page.getByText('Compute service is unavailable', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Install on HPC', exact: true })).toBeDisabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('installer.png'), fullPage: true })
})

test('constructor resumes the same background run after a page reload', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 1000 })
  await shell(page)
  await page.route(apiV2('/pipelines'), route => fulfillJson(route, { data: { pipelines: [config] } }))
  await page.route(apiV2('/pipelines/image_review'), route => fulfillJson(route, { data: { pipeline: { config } } }))
  await page.route(apiV2('/components'), route => fulfillJson(route, { data: { components: [component] } }))
  await page.route(apiV1('/sessions'), route => fulfillJson(route, { data: { sessions: [{ id: 42, name: 'Teaching models', created_at: '2026-09-26T09:00:00Z' }] } }))
  await page.route(apiV2('/pipelines/constructor/preflight'), route => fulfillJson(route, { data: { valid: true, validation: { valid: true }, steps: [], preflight_token: 'checked-files' } }))
  let submissions = 0
  let runId = ''
  let completed = false
  await page.route(apiV2('/pipelines/image_review/execute'), async route => {
    const body = route.request().postDataJSON()
    expect(body.async_execution).toBe(true)
    expect(body.expected_version).toBe('1.0.0')
    expect(body.preflight_token).toBe('checked-files')
    submissions++
    runId = body.request_id
    await fulfillJson(route, { data: { run_id: runId, status: 'pending' } }, 202)
  })
  await page.route(/\/api\/v2\/runs\//, route => fulfillJson(route, { data: { run: { run_id: runId, status: completed ? 'completed' : 'running', started_at: new Date().toISOString(), result: { progress: { total_files: 2, processed_count: 1, status_message: 'Rendering file 2 of 2' } }, steps: [] } } }))
  await page.goto('/tools/pipeline-constructor')
  await page.getByRole('button', { name: 'Diagnostics', exact: true }).click()
  await page.getByTestId('preflight-session-id').selectOption('42')
  await page.getByText('Advanced: enter file paths', { exact: true }).click()
  await page.getByTestId('preflight-local-file-paths').fill('/tmp/sample.glb')
  await page.getByRole('button', { name: 'Check selected files', exact: true }).click()
  await page.getByTestId('run-pipeline-execution').click()
  await expect(page.getByText('Rendering file 2 of 2', { exact: true })).toBeVisible()
  await expect(page.getByRole('progressbar', { name: 'Rendering file 2 of 2' })).toHaveAttribute('aria-valuenow', '50')
  await page.reload()
  await expect(page.getByText('Rendering file 2 of 2', { exact: true })).toBeVisible()
  expect(submissions).toBe(1)
  completed = true
  await page.getByRole('button', { name: 'Refresh run status', exact: true }).click()
  await expect(page.getByRole('link', { name: `Open saved run ${runId}` })).toBeVisible()
  await expect(page.getByText(/completed ·/)).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('reconnected-run.png'), fullPage: true })
})
