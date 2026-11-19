import { expect, test, type Page } from '@playwright/test'
import { apiV1, apiV2, fulfillJson, loginThroughUi, mockCurrentUser, mockLogin, mockSetupStatus } from './support/api'

async function openUpload(page: Page) {
  await page.route(/\/api\/v1\//, route => fulfillJson(route, { data: {} }))
  await mockSetupStatus(page, true)
  await mockLogin(page)
  await page.route(apiV1('/admin/storage-status'), route => fulfillJson(route, {
    data: { active_storage: 'server', active_message: 'Storage ready', config: { storage_mode: 'server_only' } },
  }))
  await page.route(apiV1('/hpc-link/status'), route => fulfillJson(route, {
    data: { enabled: true, available: true, can_allocate: true, deployment_class: 'server' },
  }))
  await loginThroughUi(page)
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: /new upload/i }).click()
  const notice = page.getByRole('button', { name: 'OK', exact: true })
  if (await notice.isVisible()) await notice.click()
}

for (const width of [320, 375, 768, 1280]) {
  test(`upload layout at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    await openUpload(page)
    await page.locator('#file-upload').setInputFiles({
      name: `${'model-with-a-long-name-'.repeat(6)}.glb`, mimeType: 'model/gltf-binary', buffer: Buffer.from('glb'),
    })
    await expect(page.getByTestId('upload-primary-action')).toBeEnabled()
    await expect(page.locator('[aria-current="step"]')).toHaveCount(1)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('upload.png'), fullPage: true })
    await page.getByTestId('upload-path-batch').click()
    await page.getByLabel('Model files ZIP').focus()
    await expect(page.getByLabel('Model files ZIP')).toBeFocused()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('batch.png'), fullPage: true })
  })
}

test('rejects multi-file drops and empty files, then allows correction and reselection', async ({ page }) => {
  await openUpload(page)
  const files = await page.evaluateHandle(() => {
    const transfer = new DataTransfer()
    transfer.items.add(new File(['obj'], 'model.obj'))
    transfer.items.add(new File(['material'], 'model.mtl'))
    return transfer
  })
  await page.getByTestId('upload-direct-dropzone').dispatchEvent('drop', { dataTransfer: files })
  await expect(page.getByRole('alert')).toContainText('Direct upload accepts one file')
  await expect(page.getByTestId('upload-primary-action')).toBeDisabled()
  await page.locator('#file-upload').setInputFiles({ name: 'empty.glb', mimeType: 'model/gltf-binary', buffer: Buffer.alloc(0) })
  await expect(page.getByTestId('upload-error')).toContainText('This file is empty')
  const file = { name: 'model.glb', mimeType: 'model/gltf-binary', buffer: Buffer.from('glb') }
  await page.locator('#file-upload').setInputFiles(file)
  await expect(page.getByTestId('upload-error')).toHaveCount(0)
  await page.getByRole('button', { name: 'Remove model.glb', exact: true }).click()
  await expect(page.getByTestId('upload-primary-action')).toBeDisabled()
  await page.locator('#file-upload').setInputFiles(file)
  await expect(page.getByTestId('upload-primary-action')).toBeEnabled()
})

test('keeps upload controls stable during transfer and restores them after failure', async ({ page }) => {
  await openUpload(page)
  let release: () => void = () => {}
  const pending = new Promise<void>(resolve => { release = resolve })
  await page.route(apiV1('/sessions/file'), async route => {
    await pending
    await fulfillJson(route, { error: { message: 'Transfer interrupted. Try again.' } }, 503)
  })
  await page.route(apiV1('/sessions/file/recover'), route => fulfillJson(route, { error: { message: 'Transfer interrupted. Select the original file to retry.', code: 'NOT_FOUND' } }, 404))
  await page.locator('#file-upload').setInputFiles({ name: 'model.glb', mimeType: 'model/gltf-binary', buffer: Buffer.from('glb') })
  await page.getByTestId('upload-primary-action').click()
  await expect(page.getByRole('progressbar')).toHaveAccessibleName('Uploading and checking your file…')
  await expect(page.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow')
  await expect(page.getByTestId('upload-path-batch')).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Remove model.glb', exact: true })).toBeDisabled()
  release()
  await expect(page.getByTestId('upload-error')).toContainText('Transfer interrupted')
  await expect(page.getByTestId('upload-primary-action')).toBeEnabled()
  await expect(page.getByTestId('upload-path-batch')).toBeEnabled()
})

test('opens file selection with the keyboard and exposes workspace settings', async ({ page }) => {
  await openUpload(page)
  await page.locator('#file-upload').focus()
  const chooser = page.waitForEvent('filechooser')
  await page.keyboard.press('Enter')
  await (await chooser).setFiles({ name: 'model.glb', mimeType: 'model/gltf-binary', buffer: Buffer.from('glb') })
  await expect(page.getByTestId('upload-primary-action')).toBeEnabled()
  await page.locator('summary').filter({ hasText: 'Workspace and destination' }).click()
  await page.getByLabel('Default Zenodo environment').selectOption('production')
  await expect(page.locator('summary').filter({ hasText: 'Workspace and destination' })).toContainText('Production')
  await page.getByRole('link', { name: 'Skip to content' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('#main-content')).toBeFocused()
})

async function seedReview(page: Page) {
  await openUpload(page)
  await mockCurrentUser(page)
  await page.addInitScript(() => {
    const file = { file_id: 1, name: 'sculpture.glb', children: [] }
    sessionStorage.setItem('workflowState', JSON.stringify({
      sessionId: 99, currentStep: 6, uploadedFiles: [file], selectedFiles: [file],
      submissionMetadata: { title: 'Sculpture study — textured model' },
      selectedPipeline: { identifier: 'render', name: 'Render thumbnails' }, isBatchMode: false,
    }))
  })
  const pipeline = { identifier: 'render', name: 'Render thumbnails', description: 'Create previews and linked metadata for your model.', version: '1.0', config: { steps: [
    { id: 'fast_renderer', name: 'Render thumbnails', enabled: true },
    { id: 'zenodo_upload', component_ref: 'zenodo_upload', name: 'Upload to Zenodo', enabled: true },
  ] } }
  await page.route(apiV2('/pipelines'), route => fulfillJson(route, { data: { pipelines: [pipeline] } }))
  await page.route(apiV2('/pipelines/render'), route => fulfillJson(route, { data: { pipeline } }))
  await page.route(apiV1('/sessions/99'), route => fulfillJson(route, { data: { session: {
    publishing_context: { default_zenodo_environment: 'sandbox', effective_credential_source: 'user' }, workspace: { type: 'personal' },
  } } }))
}

for (const width of [375, 1280]) {
  test(`pipeline and summary remain readable at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 })
    await seedReview(page)
    await page.goto('/workflow/pipeline')
    await expect(page.getByRole('radio', { name: 'Render thumbnails' })).toBeChecked()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('pipeline.png'), fullPage: true })
    await page.getByTestId('pipeline-continue').click()
    await expect(page).toHaveURL(/\/workflow\/submit$/)
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0)
    await expect(page.getByRole('radio', { name: 'Sandbox Test repository' })).toBeChecked()
    await page.getByRole('radio', { name: 'Production Zenodo repository' }).check()
    await expect(page.getByRole('radio', { name: 'Production Zenodo repository' })).toBeChecked()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.evaluate(() => window.scrollTo(0, 0))
    await page.screenshot({ path: testInfo.outputPath('summary.png'), fullPage: true })
  })
}

test('shows a lost progress connection and recovers without submitting again', async ({ page }) => {
  await seedReview(page)
  let offline = true
  await page.route(apiV1('/submissions/8/progress'), route => offline
    ? fulfillJson(route, { error: { message: 'Temporarily unavailable' } }, 503)
    : fulfillJson(route, { data: { status: 'processing', progress: { percent: 45, status_message: 'Rendering previews', current_stage: 'rendering' } } }))
  await page.goto('/workflow/submit?submissionId=8')
  await expect(page.getByText('Progress updates are temporarily unavailable.', { exact: false })).toBeVisible()
  offline = false
  await expect(page.getByRole('progressbar', { name: 'Processing progress' })).toHaveAttribute('aria-valuenow', '45')
  await expect(page.getByText('Progress updates are temporarily unavailable.', { exact: false })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Confirm & Process', exact: false })).toHaveCount(0)
})

test('guides a first upload and provides a usable batch spreadsheet example', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 375, height: 900 })
  await openUpload(page)
  await expect(page.getByRole('navigation', { name: 'Workflow progress' })).toContainText('Step 1 of 6')
  await page.getByText('Help with this step', { exact: true }).click()
  await expect(page.getByText('Use one self-contained model', { exact: false })).toBeVisible()
  await page.getByTestId('upload-path-batch').click()
  await expect(page.getByRole('navigation', { name: 'Workflow progress' })).toContainText('Step 1 of 7')
  await page.getByText('How to prepare a batch', { exact: true }).click()
  const example = page.getByRole('link', { name: 'Download example CSV' })
  const response = await page.request.get(await example.getAttribute('href') || '')
  expect(response.ok()).toBe(true)
  expect(await response.text()).toContain('filename,title,description\nmodel.obj,')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('batch-help-mobile.png'), fullPage: true })
  await page.getByTestId('upload-path-manual').click()
  await expect(page.getByText('How to prepare a batch', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('navigation', { name: 'Workflow progress' })).toContainText('Step 1 of 6')
})

test('distinguishes a dashboard loading failure from an empty workspace and allows recovery', async ({ page }) => {
  await openUpload(page)
  await mockCurrentUser(page)
  let offline = true
  await page.route(apiV1('/sessions'), route => offline
    ? fulfillJson(route, { error: { message: 'Unavailable' } }, 503)
    : fulfillJson(route, { data: { sessions: [] } }))
  await page.goto('/dashboard')
  await expect(page.locator('main').getByRole('alert')).toContainText('Could not load your sessions')
  await expect(page.getByRole('heading', { name: 'Start your first session' })).toHaveCount(0)
  offline = false
  await page.getByRole('button', { name: 'Try again', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Start your first session' })).toBeVisible()
  await page.getByRole('link', { name: 'Upload files', exact: true }).click()
  await expect(page).toHaveURL(/\/workflow\/upload$/)
})

test('selects linked metadata templates with the keyboard and updates the preview', async ({ page }, testInfo) => {
  await seedReview(page)
  const templates = [
    { id: 1, name: 'Default template', standard: 'edm', is_default: true },
    { id: 2, name: 'Collection template', standard: 'edm', is_default: false },
  ]
  await page.route(apiV1('/templates'), route => fulfillJson(route, { success: true, data: { templates } }))
  let previewTemplate = 0
  await page.route(apiV1('/templates/preview'), async route => {
    previewTemplate = (await route.request().postDataJSON()).template_id
    await fulfillJson(route, { success: true, data: { xml: '<example />' } })
  })
  await page.route(apiV1('/templates/validate'), route => fulfillJson(route, { success: true, data: { valid: true } }))
  await page.goto('/workflow/edm-selection')
  await expect(page.getByRole('radio', { name: 'Default template', exact: true })).toBeChecked()
  await page.getByRole('radio', { name: 'Collection template', exact: true }).focus()
  await page.keyboard.press('Space')
  await expect(page.getByRole('radio', { name: 'Collection template', exact: true })).toBeChecked()
  await expect.poll(() => previewTemplate).toBe(2)
  await expect(page.getByRole('navigation', { name: 'Workflow progress' })).toContainText('Step 4 of 6')
  await page.getByText('Help with this step', { exact: true }).click()
  await expect(page.getByText('EDM means Europeana Data Model.', { exact: false })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath('linked-metadata.png'), fullPage: true })
})
