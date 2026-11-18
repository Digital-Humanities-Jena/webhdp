import { expect, test, type Page } from '@playwright/test'
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
}

const baseJob = { id: 'sample-request', title: dataset.title, files: [], repairs: [], draft: null }
const completedJob = {
  ...baseJob,
  stage: 'completed',
  status: 'completed',
  files: [{ name: 'edm.xml', size: 256, format: 'EDM' }, { name: 'metadata.csv', size: 640, format: 'MSF' }],
  repairs: [{ kind: 'relinked', reference: 'texture-missing.png', replacement: 'tile-pattern.png' }],
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
}

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
  await page.getByRole('link', { name: 'Open 3D workflow' }).click()
  await expect(page).toHaveURL(/\/login\?redirect=\/model-publication$/)
  const demoUser = { ...defaultUser, model_publication_only: true }
  await mockLogin(page, { user: demoUser })
  await page.getByTestId('login-email').fill('demo@example.com')
  await page.getByTestId('login-password').fill('browser-test-password')
  await page.getByTestId('login-submit').click()
  await expect(page).toHaveURL(/\/model-publication$/)
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Account', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Upload a sample ZIP' })).toBeVisible()
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
  await page.getByRole('button', { name: 'Use Painted floor tile' }).click()
  await expect(page.getByRole('region', { name: 'Selected sample' })).toBeFocused()
  await page.getByRole('button', { name: 'Prepare Sandbox draft' }).click()
  await expect(page.getByText('3 requests are ahead of yours.', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Prepare another model' })).toHaveCount(0)
  latest = completedJob
  await expect(page.getByText('Draft ready', { exact: true })).toBeVisible()
  await expect(page.getByText('Texture relinked', { exact: true })).toBeVisible()
  await expect(page.getByText('tile-pattern.png')).toBeVisible()
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
