import { expect, test, type Page } from '@playwright/test'
import { createHash } from 'node:crypto'
import { apiV1, defaultUser, fulfillJson, mockCurrentUser, mockLogin, mockSetupStatus, seedAuthToken } from './support/api'

const dataset = {
  id: 'painted-floor-tile',
  title: 'Painted floor tile',
  creator: 'WebHDP sample collection',
  format: 'glTF',
  description: 'A small glazed tile.',
  layout: 'Nested model and textures',
  texture_status: 'Misnamed texture',
  filename: 'painted-floor-tile.zip',
  license: 'CC0',
  sha256: createHash('sha256').update('sample').digest('hex'),
  records: [{ filename: 'tile.gltf', title: 'Painted floor tile', creator: 'WebHDP sample collection', description: 'A small glazed tile.', license: 'cc0-1.0' }],
}

const baseJob = { id: 'sample-request', title: dataset.title, files: [], repairs: [], draft: null }
const completedJob = {
  ...baseJob,
  stage: 'completed',
  status: 'completed',
  model: 'tile.gltf',
  source_files: ['tile.gltf', 'tile-pattern.png'],
  files: [{ name: 'edm.xml', size: 256, format: 'EDM' }, { name: 'metadata.csv', size: 640, format: 'MSF' }],
  repairs: [
    { kind: 'relinked', reference: 'texture-missing.png', replacement: 'tile-pattern.png' },
    { kind: 'material_fallback', reason: 'unreadable_texture', reference: 'detail.png' },
  ],
  metadata: { title: dataset.title, creators: [{ name: dataset.creator }], source: 'msf', license: 'cc0-1.0' },
  draft: {
    id: 482,
    title: dataset.title,
    files: ['edm.xml', 'metadata.csv'],
    url: 'https://sandbox.zenodo.org/uploads/482',
    preview_url: 'https://sandbox.zenodo.org/records/482?preview=1&token=demo.test.signature',
  },
}

async function setup(page: Page) {
  await page.route(/\/api\/v\d\//, route => fulfillJson(route, { data: {} }))
  await mockSetupStatus(page)
  await page.addInitScript(() => localStorage.setItem('webhdp_cookie_notice_v1', 'accepted'))
  await page.route(apiV1('/model-publication/samples'), route => fulfillJson(route, {
    data: { datasets: [dataset], published_example: 'https://sandbox.zenodo.org/records/481' },
  }))
  await page.route(apiV1('/model-publication/availability'), route => fulfillJson(route, {
    data: { ready: true, credential_ready: true },
  }))
  await page.route(apiV1('/model-publication/queue'), route => fulfillJson(route, {
    data: { queued: 0, running: 0, capacity: 4, ready: true, updated: 1795000000 },
  }))
  await page.route(apiV1('/model-publication/jobs'), route => fulfillJson(route, { data: { jobs: [] } }))
}

test('lets a new user run, review, download and replay the 3D tutorial without a Sandbox key', async ({ page }) => {
  await setup(page)
  await seedAuthToken(page)
  await mockCurrentUser(page, { ...defaultUser, onboarding_required: true })
  await page.route(apiV1('/model-publication/availability'), route => fulfillJson(route, {
    data: { ready: true, practice_ready: true, credential_ready: false },
  }))
  const requestKeys: string[] = []
  const queuedPractice = { ...baseJob, run_mode: 'practice', stage: 'queued', status: 'queued', ahead: 2 }
  const finishedPractice = { ...completedJob, run_mode: 'practice', draft: null,
    files: [{ name: 'model.glb', size: 256, format: 'Model' }, { name: 'metadata.csv', size: 640, format: 'Source spreadsheet' }],
  }
  let current: typeof queuedPractice | typeof finishedPractice = queuedPractice
  await page.route(apiV1('/model-publication/jobs'), async route => {
    const request = route.request()
    if (request.method() === 'GET') {
      expect(new URL(request.url()).searchParams.get('run_mode')).toBe('practice')
      await fulfillJson(route, { data: { jobs: requestKeys.length ? [current] : [] } })
      return
    }
    expect(request.postData()).toMatch(/name="run_mode"\r\n\r\npractice/)
    expect(request.postData()).toMatch(/name="sample_id"\r\n\r\npainted-floor-tile/)
    requestKeys.push(request.headers()['idempotency-key'])
    await fulfillJson(route, { data: { job: current } }, 202)
  })
  await page.route(apiV1('/model-publication/jobs/sample-request/files/model.glb'), route => route.fulfill({
    status: 200, contentType: 'model/gltf-binary', body: 'sample GLB bytes',
  }))

  await page.goto('/tutorial/3d')
  await expect(page.getByRole('heading', { name: 'Try the 3D asset pipeline' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Selected sample' }).getByLabel('Title')).toHaveValue(dataset.title)
  await expect(page.getByRole('link', { name: 'Manage your Zenodo Sandbox key' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Run practice pipeline' }).click()
  await expect(page.getByRole('region', { name: 'Processing queue' })).toContainText('Your place in the queue is 3.')
  current = finishedPractice

  await expect(page.getByText('Practice results ready')).toBeVisible()
  await page.getByRole('button', { name: 'Inspect texture repairs' }).click()
  await expect(page.getByRole('dialog', { name: 'Texture repair details' })).toContainText('tile-pattern.png')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('heading', { name: 'Zenodo Sandbox draft' })).toHaveCount(0)
  const [download] = await Promise.all([
    page.waitForEvent('download'), page.getByRole('button', { name: 'Download model.glb' }).click(),
  ])
  expect(download.suggestedFilename()).toBe('model.glb')

  await page.reload()
  await expect(page.getByText('Practice results ready')).toBeVisible()
  await page.getByRole('button', { name: 'Run tutorial again' }).click()
  current = queuedPractice
  await page.getByRole('button', { name: 'Run practice pipeline' }).click()
  await expect.poll(() => requestKeys.length).toBe(2)
  expect(requestKeys[0]).not.toBe(requestKeys[1])
})

test('offers download links publicly and retains the workflow after sign in', async ({ page }) => {
  await setup(page)
  const downloadPath = '/model-publication/samples/painted-floor-tile'
  await page.route(apiV1(downloadPath), route => route.fulfill({
    status: 200, contentType: 'application/zip', body: 'sample ZIP bytes',
    headers: { 'content-disposition': 'attachment; filename="painted-floor-tile.zip"' },
  }))
  await page.goto('/model-publication/samples')
  await expect(page.getByRole('heading', { name: 'Sample 3D models' })).toBeVisible()
  await expect(page.getByText('Misnamed texture', { exact: true })).toBeVisible()
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('link', { name: 'Download Painted floor tile (ZIP)' }).click(),
  ])
  expect(download.suggestedFilename()).toBe('painted-floor-tile.zip')
  await expect(page.getByRole('link', { name: 'Open 3D workflow' })).toHaveAttribute('href', '/model-publication')
  await page.route(apiV1('/model-publication/jobs'), route => fulfillJson(route, { data: { jobs: [completedJob] } }))
  await page.getByRole('link', { name: 'Try Painted floor tile in WebHDP' }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('redirect')).toBe('/model-publication?sample=painted-floor-tile')
  const demoUser = { ...defaultUser, model_publication_only: true, model_publication_expires_at: 1795000900 }
  await mockLogin(page, { user: demoUser })
  await page.getByTestId('login-email').fill('demo@example.com')
  await page.getByTestId('login-password').fill('browser-test-password')
  await page.getByTestId('login-submit').click()
  await expect(page).toHaveURL(/\/model-publication\?sample=painted-floor-tile$/)
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Account', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Upload a sample ZIP' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Selected sample' }).getByLabel('Title')).toHaveValue(dataset.title)
  await expect(page.getByRole('region', { name: 'Processing queue' })).toContainText('0 waiting')
  await expect(page.getByRole('region', { name: 'Processing queue' })).toContainText('Demo access ends at')
})

test('shows queue, texture repair, private draft, and downloads, then restores on reload', async ({ page }) => {
  await setup(page)
  await page.setViewportSize({ width: 375, height: 812 })
  await seedAuthToken(page)
  await mockCurrentUser(page, { ...defaultUser, model_publication_only: true })
  const queuedJob = { ...baseJob, stage: 'queued', status: 'queued', ahead: 3 }
  let latest: typeof queuedJob | typeof completedJob = queuedJob
  let submitted = false
  await page.route(apiV1('/model-publication/jobs'), async route => {
    if (route.request().method() === 'GET') {
      await fulfillJson(route, { data: { jobs: submitted ? [latest] : [] } })
      return
    }
    expect(route.request().headers()['idempotency-key']).toMatch(/^[a-f0-9-]{36}$/)
    expect(route.request().postData()).toMatch(/name="sample_id"\r\n\r\npainted-floor-tile/)
    submitted = true
    await fulfillJson(route, { data: { job: latest } }, 202)
  })
  await page.route(apiV1('/model-publication/jobs/sample-request/files/edm.xml'), route => route.fulfill({
    status: 200, contentType: 'application/xml', body: '<rdf/>'
  }))
  await page.goto('/model-publication')
  const queue = page.getByRole('region', { name: 'Processing queue' })
  await expect(queue).toContainText('0 waiting')
  await page.getByRole('button', { name: 'Use Painted floor tile' }).click()
  await expect(page.getByRole('region', { name: 'Selected sample' })).toBeFocused()
  await expect(page.getByRole('region', { name: 'Selected sample' }).getByLabel('Creator')).toHaveValue(dataset.creator)
  await page.getByRole('button', { name: 'Prepare Sandbox draft' }).click()
  await expect(queue).toContainText('Your place in the queue is 4.')
  await expect(page.getByText('3 requests are ahead of yours.', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Prepare another model' })).toHaveCount(0)
  latest = completedJob
  await expect(page.getByText('Draft ready', { exact: true })).toBeVisible()
  await expect(page.getByText('Texture relinked', { exact: true })).toBeVisible()
  await expect(page.getByText('Unreadable texture replaced', { exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Texture repairs' }).getByText('tile-pattern.png')).toBeVisible()
  await page.getByRole('button', { name: 'Inspect texture repairs' }).click()
  const repairDetails = page.getByRole('dialog', { name: 'Texture repair details' })
  await expect(repairDetails.getByText('texture-missing.png', { exact: true })).toBeVisible()
  await expect(repairDetails.locator('dl').getByText('tile-pattern.png', { exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(repairDetails).toBeHidden()
  await page.getByRole('button', { name: 'Pipeline details' }).click()
  const pipeline = page.getByRole('dialog', { name: 'Model publication pipeline' })
  await expect(pipeline.getByText('Export a model and match its metadata', { exact: false })).toBeVisible()
  await pipeline.getByRole('button', { name: 'Close' }).click()
  await expect(page.getByText('Draft 482 · 2 files uploaded')).toBeVisible()
  await expect(page.getByText('Metadata spreadsheet (MSF)', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open private draft in Zenodo Sandbox' })).toHaveCount(0)
  const previewLink = page.getByRole('link', { name: 'Preview this draft in Zenodo Sandbox' })
  await expect(previewLink).toHaveAttribute('href', completedJob.draft.preview_url)
  await expect(previewLink).toHaveAttribute('rel', 'noopener noreferrer')
  await expect(page.getByRole('link', { name: 'View a published Sandbox example' })).toHaveAttribute('href', 'https://sandbox.zenodo.org/records/481')
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Download edm.xml' }).click(),
  ])
  expect(download.suggestedFilename()).toBe('edm.xml')
  await page.reload()
  await expect(page.getByText('Draft ready', { exact: true })).toBeVisible()
})

test('keeps the queue in view during upload setup and updates when the worker returns', async ({ page }) => {
  await setup(page)
  await page.setViewportSize({ width: 375, height: 650 })
  await seedAuthToken(page)
  await mockCurrentUser(page, { ...defaultUser, model_publication_only: true })
  let workerReady = false
  await page.route(apiV1('/model-publication/queue'), route => fulfillJson(route, {
    data: { queued: 3, running: 2, capacity: 4, ready: workerReady, updated: 1795000000 },
  }))
  await page.goto('/model-publication')
  const queue = page.getByRole('region', { name: 'Processing queue' })
  await expect(queue).toContainText('Processing is temporarily unavailable.')
  await page.getByRole('button', { name: 'Upload a sample ZIP' }).click()
  const archive = page.getByLabel('3D model file')
  await archive.setInputFiles({ name: 'bad-data.txt', mimeType: 'text/plain', buffer: Buffer.from('data') })
  await expect(archive).toHaveAttribute('aria-invalid', 'true')
  await expect(page.getByRole('alert')).toContainText('Choose a nonempty sample ZIP')
  await archive.setInputFiles({ name: 'sample.zip', mimeType: 'application/zip', buffer: Buffer.from('sample') })
  const submit = page.getByRole('button', { name: 'Prepare Sandbox draft' })
  await expect(page.getByRole('region', { name: 'Selected sample' }).getByLabel('Title')).toHaveValue(dataset.title)
  await expect(submit).toBeDisabled()
  await submit.scrollIntoViewIfNeeded()
  await expect(queue).toBeInViewport()
  workerReady = true
  await queue.getByRole('button', { name: 'Refresh queue' }).click()
  await expect(queue).toContainText('3 waiting')
  await expect(queue).toContainText('2 running')
  await expect(submit).toBeEnabled()
})

test('accepts a regular user’s GLB and sends its description to the Sandbox queue', async ({ page }) => {
  await setup(page)
  await seedAuthToken(page)
  await mockCurrentUser(page)
  let submitted = false
  await page.route(apiV1('/model-publication/jobs'), async route => {
    if (route.request().method() === 'GET') {
      await fulfillJson(route, { data: { jobs: submitted ? [completedJob] : [] } })
      return
    }
    const content = route.request().postData() || ''
    expect(content).toContain('filename="my-model.glb"')
    expect(content).toMatch(/name="metadata_source"\r\n\r\nform/)
    expect(content).toMatch(/name="title"\r\n\r\nGlazed tile/)
    expect(content).toMatch(/name="creator"\r\n\r\nExample Museum/)
    expect(content).toMatch(/name="description"\r\n\r\nA floor tile/)
    submitted = true
    await fulfillJson(route, { data: { job: completedJob } }, 202)
  })
  await page.goto('/model-publication')
  await page.getByRole('button', { name: 'Upload my model' }).click()
  await page.getByLabel('3D model file').setInputFiles({ name: 'my-model.glb', mimeType: 'model/gltf-binary', buffer: Buffer.from('model data') })
  await page.getByLabel('Title', { exact: true }).fill('Glazed tile')
  await page.getByLabel('Creator').fill('Example Museum')
  await page.getByLabel('Description').fill('A floor tile')
  await page.getByRole('button', { name: 'Prepare Sandbox draft' }).click()
  await expect(page.getByRole('link', { name: 'Open private draft in Zenodo Sandbox' })).toHaveAttribute('href', completedJob.draft.url)
})
