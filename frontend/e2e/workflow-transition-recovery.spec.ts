import { expect, test, type Page } from '@playwright/test'
import { apiV1, apiV2, fulfillJson, loginThroughUi, mockCurrentUser, mockLogin, mockSetupStatus } from './support/api'

async function shell(page: Page) {
  await page.route(/\/api\/v[12]\//, route => fulfillJson(route, { data: {} }))
  await mockSetupStatus(page, true)
  await mockLogin(page)
  await mockCurrentUser(page)
  await page.route(apiV1('/hpc-link/status'), route => fulfillJson(route, { data: { enabled: false, deployment_class: 'workstation-local' } }))
  await loginThroughUi(page)
  const notice = page.getByRole('button', { name: 'OK', exact: true })
  if (await notice.isVisible()) await notice.click()
}

for (const width of [375, 1280]) {
  test(`lost single-file acknowledgement recovers once at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await shell(page)
    let uploads = 0
    let token = ''
    await page.route(apiV1('/sessions/file'), async route => {
      uploads++
      token = route.request().postData()?.match(/name="submit_token"\r\n\r\n([^\r]+)/)?.[1] || ''
      await route.abort('connectionfailed')
    })
    await page.route(apiV1('/sessions/file/recover'), async route => {
      expect(route.request().postDataJSON().submit_token).toBe(token)
      await fulfillJson(route, { data: { session_id: 42, status: 'completed', foundFiles: [{ file_id: 1, name: 'model.glb', filename: 'model.glb' }] } })
    })
    await page.locator('#file-upload').setInputFiles({ name: 'model.glb', mimeType: 'model/gltf-binary', buffer: Buffer.from('glb') })
    await page.getByTestId('upload-primary-action').click()
    await expect(page).toHaveURL(/\/workflow\/files/)
    expect(uploads).toBe(1)
    expect(token).toBeTruthy()
    expect(await page.evaluate(() => sessionStorage.getItem('single_upload_state:1'))).toBeNull()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  })

  test(`revoked run access stops the loader and keeps one recovery message at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    await shell(page)
    await page.evaluate(() => {
      sessionStorage.setItem('guided-pipeline-run:42', JSON.stringify({ runId: 'accepted-run', confirmed: true }))
      sessionStorage.setItem('workflowState', JSON.stringify({ sessionId: 42, currentStep: 7, uploadedFiles: [], selectedFiles: [], submissionMetadata: {}, selectedPipeline: { identifier: 'render', name: 'Render' }, isBatchMode: false }))
    })
    let reads = 0
    await page.route(apiV2('/runs/accepted-run'), route => {
      reads++
      return fulfillJson(route, { error: { code: 'FORBIDDEN', message: 'Access revoked' } }, 403)
    })
    await page.goto('/workflow/submit?sessionId=42')
    await expect(page.getByText('Progress monitoring stopped', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Check access again' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Return to sessions' })).toHaveAttribute('href', '/dashboard')
    await expect(page.getByRole('progressbar')).toHaveCount(0)
    await page.waitForTimeout(2200)
    expect(reads).toBe(1)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('stopped-monitor.png'), fullPage: true })
  })

  test(`changed validation policy uses the existing metadata panel at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    await shell(page)
    await page.route(apiV1('/sessions/42/records/1'), route => fulfillJson(route, { data: {
      session: { id: 42 }, record: { local_record_id: 1, record_title: 'Museum object', record_status: 'draft' }, health: {}, lineage: {}, files: [],
    } }))
    let retried = false
    await page.route(apiV1('/sessions/42/records/1/lod'), route => {
      if (route.request().method() === 'POST') retried = true
      return fulfillJson(route, { data: { available: true,
        readiness: { ready: retried, state: retried ? 'uploaded' : 'blocked', revalidation_required: !retried },
        formats: { edm: retried ? { status: 'generated', success: true } : { status: 'revalidation_required', success: false } },
      } })
    })
    await page.goto('/sessions/42/records/1')
    await expect(page.getByText('Validation requirements changed. Revalidate metadata before continuing.', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Download EDM' })).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: testInfo.outputPath('revalidation.png'), fullPage: true })
    await page.getByRole('button', { name: 'Revalidate metadata' }).click()
    await expect(page.getByRole('button', { name: 'Download EDM' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Revalidate metadata' })).toHaveCount(0)
  })
}
