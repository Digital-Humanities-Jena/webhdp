import { expect, test } from '@playwright/test'
import { adminUser, apiV1, fulfillJson, loginThroughUi, mockCurrentUser, mockLogin, mockSetupStatus } from './support/api'

for (const width of [375, 1280]) {
  test(`reconnects an uncertain Zenodo draft at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    await page.route(/\/api\/v[12]\//, route => fulfillJson(route, { data: {} }))
    await mockSetupStatus(page, true)
    await mockLogin(page, { user: adminUser })
    await mockCurrentUser(page, adminUser)
    await loginThroughUi(page, { email: adminUser.email })
    const notice = page.getByRole('button', { name: 'OK', exact: true })
    if (await notice.isVisible()) await notice.click()
    let reconnected = false
    await page.route(apiV1('/sessions/42/records/1'), route => fulfillJson(route, { data: {
      session: { id: 42, permissions: { can_edit: true } }, record: { local_record_id: 1, record_title: 'Museum object', record_status: reconnected ? 'draft' : 'prepared' },
      health: {}, lineage: {}, files: [], zenodo_status: { unresolved_operations: reconnected ? [] : [{ operation_id: 'creation', operation_type: 'create_draft', remote_id: null }] },
    } }))
    await page.route(apiV1('/sessions/42/records/1/lod'), route => fulfillJson(route, { data: { available: false, formats: {}, readiness: { ready: true } } }))
    await page.route(apiV1('/sessions/42/records/1/reconcile'), async route => {
      expect(route.request().postDataJSON()).toEqual({ deposition_id: '9001', confirmed_not_created: false })
      reconnected = true
      await fulfillJson(route, { data: { success: true } })
    })
    await page.goto('/sessions/42/records/1')
    await expect(page.getByRole('heading', { name: 'Zenodo response could not be confirmed' })).toBeVisible()
    await page.getByLabel('Zenodo draft ID').fill('9001')
    await page.getByRole('button', { name: 'Reconnect draft', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Zenodo response could not be confirmed' })).toHaveCount(0)
    expect(reconnected).toBe(true)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  })
}
