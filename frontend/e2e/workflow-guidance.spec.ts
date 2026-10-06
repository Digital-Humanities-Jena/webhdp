import { expect, test, type Page } from '@playwright/test'
import { apiV1, apiV2, fulfillJson, mockCurrentUser, mockSetupStatus, seedAuthToken } from './support/api'

const file = { file_id: 101, name: 'model.glb', filename: 'model.glb', children: [] }

async function seedWorkflow(page: Page, batch = false, files = [file], pipeline: { identifier: string, name: string } | null = null) {
  await page.route(/\/api\/v\d\//, route => fulfillJson(route, { data: {} }))
  await mockSetupStatus(page)
  await mockCurrentUser(page)
  await seedAuthToken(page)
  await page.addInitScript(({ batch, files, pipeline }) => {
    localStorage.setItem('webhdp_cookie_notice_v1', 'accepted')
    sessionStorage.setItem('workflowState', JSON.stringify({ sessionId: 42, currentStep: pipeline ? 7 : 4,
      uploadedFiles: files, selectedFiles: files, selectedPipeline: pipeline,
      submissionMetadata: pipeline ? { title: 'Museum model' } : {}, isBatchMode: batch,
      msfPath: batch ? '/session/metadata.csv' : null, msfMapping: {}, fileMetadataMap: {} }))
  }, { batch, files, pipeline })
  await page.route(apiV1('/admin/storage-status'), route => fulfillJson(route, {
    data: { active_storage: 'server', config: { storage_mode: 'server_only' } },
  }))
  await page.route(apiV1('/metadata/zenodo-community-override'), route => fulfillJson(route, { data: { config: { enabled: false } } }))
  await page.route(apiV1('/metadata/schema'), route => fulfillJson(route, { data: {
    standard_fields: [{ key: 'title', label: 'Title', type: 'text', mandatory: true }], complex_fields: {}, vocabularies: {},
  } }))
}

test('flushes edits when leaving metadata through the sidebar', async ({ page }) => {
  await seedWorkflow(page)
  let title = 'Original title'
  let writes = 0
  await page.route(apiV1('/metadata/user/42'), route => fulfillJson(route, { data: { metadata: { zenodo_metadata_draft: { title } } } }))
  await page.route(apiV1('/metadata/user/42/draft'), async route => {
    title = route.request().postDataJSON().title
    writes++
    await fulfillJson(route, { data: {} })
  })
  await page.goto('/workflow/metadata')
  await page.getByRole('textbox', { name: /^Title/ }).fill('Latest title')
  await page.locator('a[href="/dashboard"]').click()
  await expect(page).toHaveURL(/\/dashboard$/)
  expect(writes).toBe(1)
  await page.goto('/workflow/metadata')
  await expect(page.getByRole('textbox', { name: /^Title/ })).toHaveValue('Latest title')
})

test('restores unsent edits after reload and keeps drafts separate between users', async ({ page }) => {
  await seedWorkflow(page)
  await page.route(apiV1('/metadata/user/42'), route => fulfillJson(route, { data: { metadata: { zenodo_metadata_draft: { title: 'Server title' } } } }))
  await page.route(apiV1('/metadata/user/42/draft'), route => fulfillJson(route, { error: { message: 'Storage unavailable' } }, 503))
  await page.goto('/workflow/metadata')
  await page.getByRole('textbox', { name: /^Title/ }).fill('Unsent title')
  await page.reload()
  await expect(page.getByRole('textbox', { name: /^Title/ })).toHaveValue('Unsent title')
  await expect(page.getByText('Recovered draft · awaiting save', { exact: true })).toBeVisible()
  await mockCurrentUser(page, { id: 2, email: 'second@example.com', role: 'user', capabilities: [], groups: [], institutions: [], memberships: [] })
  await page.reload()
  await expect(page.getByRole('textbox', { name: /^Title/ })).toHaveValue('Server title')
})

test('focuses invalid metadata and links the error to its field', async ({ page }) => {
  await seedWorkflow(page)
  await page.goto('/workflow/metadata')
  await page.getByRole('button', { name: 'Save & Continue', exact: false }).click()
  const title = page.getByRole('textbox', { name: /^Title/ })
  await expect(title).toBeFocused()
  await expect(title).toHaveAttribute('aria-invalid', 'true')
  await expect(title).toHaveAttribute('aria-describedby', 'field-title-error')
  await expect(page.locator('#field-title-error')).toHaveText('Title is required.')
})

test('retains the metadata view when both server and browser draft storage fail', async ({ page }) => {
  await seedWorkflow(page)
  await page.addInitScript(() => {
    const setItem = Storage.prototype.setItem
    Storage.prototype.setItem = function(key, value) {
      if (key.startsWith('webhdp:metadata-draft:')) throw new DOMException('Storage full', 'QuotaExceededError')
      return setItem.call(this, key, value)
    }
  })
  await page.route(apiV1('/metadata/user/42/draft'), route => fulfillJson(route, { error: { message: 'Storage unavailable' } }, 503))
  await page.goto('/workflow/metadata')
  await page.getByRole('textbox', { name: /^Title/ }).fill('Unsent title')
  await page.locator('a[href="/dashboard"]').click()
  await expect(page.getByText('Draft save failed.', { exact: false })).toBeVisible()
  await expect(page).toHaveURL(/\/workflow\/metadata$/)
  await expect(page.getByRole('textbox', { name: /^Title/ })).toHaveValue('Unsent title')
})

for (const width of [320, 375, 768, 1280]) {
  test(`batch mapping controls remain accessible at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    await seedWorkflow(page, true)
    await page.route(apiV1('/templates'), route => fulfillJson(route, { success: true, data: { templates: [{ id: 1, name: 'Default', standard: 'edm', is_default: true, content: '<rdf/>' }] } }))
    await page.route(apiV1('/edm/msf-columns'), route => fulfillJson(route, { success: true, data: {
      columns: ['filename', 'title', 'description', 'creator'], suggested_row_index: 0,
      sample_records: [{ row_index: 0, filename: 'model.glb', label: 'model.glb · row 1' }, { row_index: 1, filename: 'nested/模型.glb', label: 'nested/模型.glb · row 2' }],
      quality_summary: { row_count: 2, missing: { filename: 0, title: 0, description: 1, creators: 1 }, duplicate_source_count: 0, scope: 'Spreadsheet values before defaults.' },
    } }))
    await page.route(apiV1('/metadata/test-mapping'), route => fulfillJson(route, { success: true, data: {
      row_index_used: 1, source_filename: 'nested/模型.glb', metadata: { title: 'Museum model', description: 'A model', creators: [{ name: 'Museum' }], license: 'cc-by-4.0' },
      provenance: { title: { source: 'mapped', field: 'title' }, license: { source: 'default' } }, validation: { valid: true },
    } }))
    await page.goto('/workflow/edm-selection')
    await expect(page.locator('.mapping-row').first()).toBeVisible()
    const controls = page.locator('.mapping-row select, .mapping-row input')
    for (const control of await controls.all()) {
      await expect(control).toHaveAccessibleName(/.+/)
      const bounds = await control.boundingBox()
      expect(bounds?.x).toBeGreaterThanOrEqual(0)
      expect((bounds?.x || 0) + (bounds?.width || 0)).toBeLessThanOrEqual(width)
    }
    await page.getByLabel('Preview record', { exact: true }).selectOption('1')
    await page.getByRole('button', { name: 'Test Mapping', exact: true }).click()
    await expect(page.getByTestId('metadata-review')).toContainText('Museum model')
    await expect(page.getByTestId('metadata-review')).toContainText('Default')
    await expect(page.getByTestId('metadata-review')).toContainText('nested/模型.glb')
    await page.locator('.mapping-row select').first().focus()
    await expect(page.locator('.mapping-row select').first()).toBeFocused()
    await page.screenshot({ path: testInfo.outputPath('batch-mapper.png'), fullPage: true })
  })
}

test('keeps a failed file list distinct from an empty directory and retries', async ({ page }) => {
  await seedWorkflow(page, false, [])
  let offline = true
  await page.route(apiV1('/sessions/42/nodes'), route => offline
    ? fulfillJson(route, { error: { message: 'Unavailable' } }, 503)
    : fulfillJson(route, { data: { nodes: [file] } }))
  await page.goto('/workflow/files')
  await expect(page.getByRole('alert')).toContainText('Could not refresh your files')
  await expect(page.getByText('No bundles found in the scanned directory.')).toHaveCount(0)
  offline = false
  await page.getByRole('button', { name: 'Try loading files again', exact: true }).click()
  await expect(page.getByRole('heading', { name: /model\.glb/ })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
})

test('recommends a compatible pipeline and explains its publication outcome', async ({ page }) => {
  await seedWorkflow(page)
  await page.route(apiV2('/pipelines'), route => fulfillJson(route, { data: { pipelines: [
    { identifier: 'render', name: 'Render', config: { steps: [{ id: 'fast_renderer' }, { id: 'zenodo_upload', parameters: { publish: true } }] } },
    { identifier: 'metadata_only', name: 'Metadata Only', config: { steps: [{ id: 'zenodo_draft' }, { id: 'zenodo_upload', parameters: { publish: false } }] } },
  ] } }))
  await page.goto('/workflow/pipeline')
  await expect(page.getByRole('radio', { name: 'Metadata Only' })).toBeChecked()
  await expect(page.getByText('Uploads files to a Zenodo draft; publication is a separate action')).toBeVisible()
  await page.getByText('Outputs and requirements').last().click()
  await expect(page.getByText('Requires: Zenodo credential for the selected environment.')).toBeVisible()
})

const localReady = { ready: true, blockers: [], selected_count: 1, pipeline_version: '1.0.0',
  readiness_token: 'current-settings', unverified: [{ message: 'Compute connectivity and generated outputs still need runtime checks.' }] }
const blocked = { ...localReady, ready: false, readiness_token: null, blockers: [{
  source: 'collection/模型.glb', message: 'Supply the required creators.', route: '/workflow/metadata',
}] }

async function seedSubmission(page: Page, compute = false) {
  const pipeline = { identifier: 'render', name: 'Prepare model' }
  await seedWorkflow(page, false, [{ ...file, absolute_path: '/session/uploads/model.glb' }], pipeline)
  await page.route(apiV1('/sessions/42'), route => fulfillJson(route, { data: { session: {
    id: 42, publishing_context: { default_zenodo_environment: 'sandbox' },
  } } }))
  await page.route(apiV1('/sessions/42/records'), route => fulfillJson(route, { data: { records: [] } }))
  const config = { name: pipeline.name, steps: [
    { id: compute ? 'fast_renderer' : 'lod_generation', enabled: true, name: 'Prepare model' },
    { id: 'zenodo_draft', enabled: true, name: 'Create draft' },
  ] }
  await page.route(apiV2('/pipelines'), route => fulfillJson(route, { data: { pipelines: [pipeline] } }))
  await page.route(apiV2('/pipelines/render'), route => fulfillJson(route, { data: { pipeline: { ...pipeline, version: '1.0.0', config } } }))
}

for (const width of [320, 1280]) {
  test(`readiness links corrections and keeps runtime details collapsed at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    await seedSubmission(page)
    let corrected = false
    await page.route(apiV2('/pipelines/render/readiness'), route => fulfillJson(route, { data: corrected ? localReady : blocked }))
    await page.goto('/workflow/submit')
    const readiness = page.getByTestId('submission-readiness')
    await expect(readiness).toContainText('collection/模型.glb')
    await expect(page.getByRole('link', { name: 'Review metadata', exact: true })).toHaveAttribute('href', '/workflow/metadata')
    await expect(page.getByTestId('submit-confirm')).toBeDisabled()
    await expect(readiness.locator('details')).not.toHaveAttribute('open')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('submission-readiness.png'), fullPage: true })
    corrected = true
    await page.getByRole('button', { name: 'Check again', exact: true }).click()
    await expect(readiness).toContainText('Local checks passed for 1 selected source.')
    await expect(page.getByTestId('submit-confirm')).toBeEnabled()
    await readiness.getByText('Checks still unverified', { exact: true }).click()
    await expect(readiness.getByText(localReady.unverified[0].message)).toBeVisible()
  })

  test(`submission rechecks before any allocation or execution at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await seedSubmission(page, true)
    let checks = 0
    let resourceRequests = 0
    await page.route(apiV2('/pipelines/render/readiness'), route => fulfillJson(route, { data: ++checks === 1 ? localReady : blocked }))
    await page.route(apiV1('/hpc-link/status'), route => { resourceRequests++; return fulfillJson(route, { data: {} }) })
    await page.route(apiV1('/hpc-link/allocations'), route => { resourceRequests++; return fulfillJson(route, { data: {} }) })
    await page.route(apiV2('/pipelines/render/execute'), route => { resourceRequests++; return fulfillJson(route, { data: {} }) })
    await page.goto('/workflow/submit')
    await expect(page.getByTestId('submit-confirm')).toBeEnabled()
    await page.getByTestId('submit-confirm').click()
    await expect(page.getByTestId('submission-readiness')).toContainText('Supply the required creators.')
    await expect(page.getByTestId('submit-confirm')).toBeDisabled()
    expect(checks).toBe(2)
    expect(resourceRequests).toBe(0)
    expect(await page.evaluate(() => sessionStorage.getItem('guided-pipeline-run:42'))).toBeNull()
  })
}

test('readiness outages retry inline and rejected stale execution requires another check', async ({ page }) => {
  await seedSubmission(page)
  let offline = true
  await page.route(apiV2('/pipelines/render/readiness'), route => offline
    ? fulfillJson(route, { error: { message: 'Readiness service unavailable' } }, 503)
    : fulfillJson(route, { data: localReady }))
  await page.route(apiV2('/pipelines/render/execute'), route => fulfillJson(route, { error: {
    code: 'OPERATION_CONFLICT', message: 'The source changed. Check readiness again.', details: { readiness_stale: true },
  } }, 409))
  await page.goto('/workflow/submit')
  await expect(page.getByTestId('submission-readiness').getByRole('alert')).toHaveText('Readiness service unavailable')
  await expect(page.getByTestId('submit-confirm')).toBeDisabled()
  offline = false
  await page.getByRole('button', { name: 'Check again', exact: true }).click()
  await expect(page.getByTestId('submit-confirm')).toBeEnabled()
  await page.getByTestId('submit-confirm').click()
  await expect(page.getByTestId('submission-readiness')).toContainText('The source changed. Check readiness again.')
  await expect(page.getByTestId('submit-confirm')).toBeDisabled()
  expect(await page.evaluate(() => sessionStorage.getItem('guided-pipeline-run:42'))).toBeNull()
})

test('a late readiness response cannot validate a changed destination', async ({ page }) => {
  await seedSubmission(page)
  let releaseFirst: (() => void) | undefined
  const firstResponse = new Promise<void>(resolve => { releaseFirst = resolve })
  let requests = 0
  await page.route(apiV2('/pipelines/render/readiness'), async route => {
    if (++requests === 1) {
      await firstResponse
      await fulfillJson(route, { data: localReady })
    } else {
      expect(route.request().postDataJSON().is_sandbox).toBe(false)
      await fulfillJson(route, { data: blocked })
    }
  })
  await page.goto('/workflow/submit')
  await expect(page.getByTestId('submission-readiness')).toHaveAttribute('aria-busy', 'true')
  const cancelled = page.waitForEvent('requestfailed', request => new URL(request.url()).pathname.endsWith('/pipelines/render/readiness'))
  await page.getByRole('radio', { name: /Production/ }).check()
  await cancelled
  await expect(page.getByTestId('submission-readiness')).toContainText('Supply the required creators.')
  releaseFirst?.()
  await expect(page.getByTestId('submission-readiness')).toContainText('Supply the required creators.')
  await expect(page.getByTestId('submit-confirm')).toBeDisabled()
})

test('reload reconnects an accepted run without new readiness or submission', async ({ page }) => {
  await seedSubmission(page)
  let checks = 0
  let executions = 0
  await page.route(apiV2('/pipelines/render/readiness'), route => { checks++; return fulfillJson(route, { data: localReady }) })
  await page.route(apiV2('/pipelines/render/execute'), route => {
    executions++
    expect(route.request().postDataJSON().readiness_token).toBe(localReady.readiness_token)
    return fulfillJson(route, { data: { run_id: 'accepted-readiness-run' } }, 202)
  })
  await page.route(apiV2('/runs/accepted-readiness-run'), route => fulfillJson(route, { data: {
    run: { public_id: 'accepted-readiness-run', status: 'pending', progress: { status_message: 'Waiting for processing' } },
  } }))
  await page.goto('/workflow/submit')
  await expect(page.getByTestId('submit-confirm')).toBeEnabled()
  await page.getByTestId('submit-confirm').click()
  await expect.poll(() => executions).toBe(1)
  await expect.poll(() => page.evaluate(() => JSON.parse(sessionStorage.getItem('guided-pipeline-run:42') || '{}').confirmed)).toBe(true)
  const originalChecks = checks
  await page.reload()
  await expect(page.getByTestId('submission-readiness')).toHaveCount(0)
  expect(executions).toBe(1)
  expect(checks).toBe(originalChecks)
})
