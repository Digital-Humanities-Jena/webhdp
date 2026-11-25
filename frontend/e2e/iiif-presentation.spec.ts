import { fileURLToPath } from 'node:url'
import { readFileSync } from 'node:fs'
import { expect, type Page, test } from '@playwright/test'
import { adminUser, apiV1, fulfillJson, mockCurrentUser, mockSetupStatus, seedAuthToken } from './support/api'

const containerId = 'https://example.org/iiif/item/1'
const presentation = (version: 3 | 4, container: object) => ({
  '@context': `http://iiif.io/api/presentation/${version}/context.json`,
  type: 'Manifest',
  label: { en: ['Museum object'] },
  id: 'https://example.org/manifest.json',
  items: [{ id: containerId, ...container }],
})

const modelScene = (assetUrl: string) => presentation(4, { type: 'Scene', items: [{
  id: `${containerId}/page/1`,
  type: 'AnnotationPage',
  items: [{
    id: `${containerId}/annotation/1`,
    type: 'Annotation',
    motivation: ['painting'],
    body: { type: 'Model', id: assetUrl, format: 'model/gltf-binary' },
    target: { type: 'Scene', id: containerId },
  }],
}] })

async function mockShell(page: Page) {
  await page.route(/\/api\/v[12]\//, route => fulfillJson(route, { success: true, data: {} }))
  await mockSetupStatus(page)
  await mockCurrentUser(page, adminUser)
  await seedAuthToken(page)
}

async function serveWithCsp(page: Page, pattern: string, sameOriginOnly = false) {
  const nginx = readFileSync(new URL('../nginx.conf', import.meta.url), 'utf8')
  const csp = nginx.match(/^    add_header Content-Security-Policy "([^"]+)"/m)?.[1]
  if (!csp) throw new Error('Could not read the application CSP')
  await page.route(pattern, async (route) => {
    const response = await route.fetch()
    await route.fulfill({
      response,
      headers: { ...response.headers(), 'Content-Security-Policy': sameOriginOnly ? csp.replace(/connect-src [^;]+;/, "connect-src 'self';") : csp },
    })
  })
}

test('admin previews the bundled Scene model and validates the rendered JSON', async ({ page }, testInfo) => {
  test.setTimeout(60_000)
  await mockShell(page)
  if (testInfo.project.name.endsWith('-csp')) await serveWithCsp(page, '**/settings/edm-templates', true)
  const template = '{"type":"Manifest","items":[]}'
  let json = ''
  await page.route(apiV1('/templates'), route => fulfillJson(route, {
    success: true,
    data: { templates: [{ id: 1, standard: 'iiif', name: 'Museum Scene', content: template }] },
  }))
  await page.route(apiV1('/templates/preview'), route => {
    const assetUrl = route.request().postDataJSON().zenodo.files[0].content_url
    expect(assetUrl).toBe('https://example.invalid/webhdp/iiif-preview.glb')
    json = JSON.stringify(modelScene(assetUrl))
    return fulfillJson(route, { success: true, data: { json } })
  })
  await page.route(apiV1('/templates/validate'), route => {
    expect(route.request().postDataJSON()).toEqual({ standard: 'iiif', json })
    return fulfillJson(route, {
      success: true,
      data: { valid: true, details: { scope: 'Local IIIF structure checks' }, errors: [], warnings: [] },
    })
  })
  await page.goto('/settings/edm-templates')
  await page.getByRole('button', { name: 'Edit', exact: true }).click()
  await expect(page.getByLabel('Content (Jinja2 JSON)')).toHaveValue(template)
  await page.getByRole('button', { name: 'Preview Render' }).click()
  await expect(page.locator('p').getByText('IIIF Presentation 4.0 RC', { exact: true })).toBeVisible()
  await expect(page.locator('model-viewer')).toHaveCount(0)
  const assetRequested = page.waitForRequest(request => /\/iiif-preview[^/]*\.glb(?:\?.*)?$/.test(request.url()))
  await page.getByRole('button', { name: 'Preview model asset' }).click()
  const assetUrl = (await assetRequested).url()
  expect(new URL(assetUrl).origin).toBe(new URL(page.url()).origin)
  await expect(page.locator('model-viewer')).toHaveJSProperty('src', assetUrl, { timeout: 15_000 })
  await expect(page.locator('model-viewer')).toHaveJSProperty('loaded', true, { timeout: 15_000 })
  await page.getByRole('button', { name: 'Validate', exact: true }).click()
  await expect(page.getByText('Local IIIF structure checks')).toBeVisible()
})

test('production CSP decodes a Draco model from an approved Zenodo path and blocks unrelated paths', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.endsWith('-csp'), 'Run using playwright.iiif-csp.config.ts')
  test.setTimeout(60_000)
  await mockShell(page)
  await serveWithCsp(page, '**/sessions/42/records/1')
  const publicFile = 'https://zenodo.org/api/records/42/files/model.glb/content'
  const forbiddenPath = 'https://zenodo.org/api/deposit/depositions/42/files/model.glb'
  const fixturePath = fileURLToPath(new URL('./fixtures/iiif-draco.glb', import.meta.url))
  const decoderRequests = new Set<string>()
  page.on('request', (request) => {
    if (/draco[^/]*(?:\.wasm|\.js)$/.test(request.url())) decoderRequests.add(request.url())
  })
  await page.route(publicFile, route => route.fulfill({
    path: fixturePath, contentType: 'model/gltf-binary', headers: { 'Access-Control-Allow-Origin': '*' }
  }))
  let forbiddenRequests = 0
  await page.route(forbiddenPath, route => { forbiddenRequests++; return route.abort() })
  await page.route(apiV1('/sessions/42/records/1'), route => fulfillJson(route, {
    data: { session: { id: 42 }, record: { local_record_id: 1, record_title: 'Museum record' } },
  }))
  let assetUrl = publicFile
  await page.route(apiV1('/sessions/42/records/1/lod'), route => {
    const format = new URL(route.request().url()).searchParams.get('format')
    return format ? fulfillJson(route, modelScene(assetUrl)) : fulfillJson(route, {
      data: { available: true, formats: { iiif: { status: 'generated', success: true } } },
    })
  })
  await page.goto('/sessions/42/records/1')
  await page.getByRole('button', { name: 'Preview IIIF manifest' }).click()
  await page.getByRole('button', { name: 'Preview model asset' }).click()
  await expect(page.locator('model-viewer')).toHaveJSProperty('loaded', true, { timeout: 15_000 })
  const decoderOrigin = new URL('/model-decoders/draco/', page.url()).href
  expect(decoderRequests).toEqual(new Set([
    `${decoderOrigin}draco_wasm_wrapper.js`, `${decoderOrigin}draco_decoder.wasm`,
  ]))
  await page.getByRole('button', { name: 'Hide IIIF manifest' }).click()
  assetUrl = forbiddenPath
  await page.getByRole('button', { name: 'Preview IIIF manifest' }).click()
  await expect(page.getByRole('link', { name: 'Open model file' })).toHaveAttribute('href', forbiddenPath)
  await expect(page.getByRole('button', { name: 'Preview model asset' })).toHaveCount(0)
  const blockedDirective = await page.evaluate(url => new Promise(resolve => {
    const timeout = window.setTimeout(() => resolve(null), 3000)
    window.addEventListener('securitypolicyviolation', event => {
      window.clearTimeout(timeout)
      resolve(event.effectiveDirective)
    }, { once: true })
    void fetch(url).catch(() => {})
  }), forbiddenPath)
  expect(blockedDirective).toBe('connect-src')
  expect(forbiddenRequests).toBe(0)
})

test('a record distinguishes current audio and historical Canvas manifests', async ({ page }) => {
  await mockShell(page)
  await page.route(apiV1('/sessions/42/records/1'), route => fulfillJson(route, {
    data: { session: { id: 42 }, record: { local_record_id: 1, record_title: 'Museum record' } },
  }))
  let manifest = presentation(3, { type: 'Canvas', width: 640, height: 480, items: [] })
  await page.route(apiV1('/sessions/42/records/1/lod'), route => {
    const format = new URL(route.request().url()).searchParams.get('format')
    return format ? fulfillJson(route, manifest) : fulfillJson(route, {
      data: { available: true, formats: { iiif: { status: 'generated', success: true } } },
    })
  })
  await page.goto('/sessions/42/records/1')
  await page.getByRole('button', { name: 'Preview IIIF manifest' }).click()
  await expect(page.getByText('IIIF Presentation 3.0', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Preview model asset' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Hide IIIF manifest' }).click()
  manifest = presentation(4, { type: 'Timeline', duration: 15, items: [{
    id: `${containerId}/page/1`,
    type: 'AnnotationPage',
    items: [{
      id: `${containerId}/annotation/1`,
      type: 'Annotation',
      motivation: ['painting'],
      body: { type: 'Audio', id: 'https://example.org/recording.mp3', format: 'audio/mpeg' },
      target: { type: 'Timeline', id: containerId },
    }],
  }] })
  await page.getByRole('button', { name: 'Preview IIIF manifest' }).click()
  await expect(page.getByText('IIIF Presentation 4.0 RC', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Preview model asset' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Download IIIF' })).toBeVisible()
})
