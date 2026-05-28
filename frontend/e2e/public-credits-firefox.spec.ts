import { expect, test } from '@playwright/test'

import { mockSetupStatus } from './support/api'

test.skip(({ browserName }) => browserName !== 'firefox', 'Firefox-only public credits verification')

test.describe('Public credits and attribution surfaces', () => {
  test('renders landing, credits, and impressum', async ({ page }) => {
    await mockSetupStatus(page, true)

    await page.goto('/')
    await expect(page.getByRole('link', { name: 'View credits' })).toBeVisible()

    await page.goto('/credits')
    await expect(page.getByRole('heading', { name: 'Credits' })).toBeVisible()
    await expect(page.getByText('Dominik Ukolov')).toBeVisible()
    await expect(page.getByText('Professorship for Digital Humanities (Image/Object), Friedrich Schiller University Jena')).toBeVisible()
    await expect(page.getByText('Research Group DIGITAL ORGANOLOGY, Leipzig University')).toBeVisible()
    await expect(page.getByText('ORCID 0000-0002-7904-3892')).toBeVisible()
    await expect(page.getByText('No. 101173385', { exact: true })).toBeVisible()
    await expect(page.getByText('No. 101233051', { exact: true })).toBeVisible()

    await page.goto('/impressum')
    await expect(page.getByText('Grant Agreement No. 101173385')).toBeVisible()
    await expect(page.getByText('Grant Agreement No. 101233051')).toBeVisible()
    await expect(page.getByRole('link', { name: 'WebHDP credits page' })).toBeVisible()
  })
})
