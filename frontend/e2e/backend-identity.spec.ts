import { expect, test, type Page } from '@playwright/test'
import { mockSetupStatus, seedAuthToken } from './support/api'

const backend = 'http://127.0.0.1:4876'
test.skip(!process.env.WEBHDP_BROWSER_TESTING, 'Run with the isolated backend browser configuration.')

async function openWorkspace(page: Page, token: string) {
  await mockSetupStatus(page)
  await seedAuthToken(page, token)
  await page.goto('/account/institutions')
  await expect(page.getByRole('heading', { name: 'Institution Workspaces', exact: true })).toBeVisible()
}

test('an institution invitation can be sent before sign-up and accepted by its verified recipient', async ({ page, browser, request }) => {
  const fixture = await (await request.post(backend + '/__test__/identity/fixture')).json()
  const name = 'Museum ' + crypto.randomUUID().slice(0, 8)
  await openWorkspace(page, fixture.admin_token)
  await page.getByRole('textbox', { name: 'New institution name' }).fill(name)
  await page.getByRole('button', { name: 'Create institution' }).click()
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Invite someone' })).toBeVisible()

  await page.getByLabel('Email address', { exact: true }).fill(fixture.invited_email)
  await page.getByRole('button', { name: 'Send invitation', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Invitation email sent.' })).toBeVisible()
  const invitation = await (await request.get(backend + '/__test__/identity/mail', {
    params: { email: fixture.invited_email, kind: 'invitation' },
  })).json()

  const context = await browser.newContext()
  try {
    const recipient = await context.newPage()
    await mockSetupStatus(recipient)
    await recipient.goto(invitation.url)
    await expect(recipient).toHaveURL(/\/institution-invitation$/)
    await recipient.getByRole('link', { name: 'Create an account' }).click()
    await recipient.getByLabel('Email address', { exact: true }).fill(fixture.invited_email)
    await recipient.getByRole('button', { name: 'Send verification email' }).click()
    await expect(recipient.getByRole('heading', { name: 'Check your inbox' })).toBeVisible()
    const verification = await (await request.get(backend + '/__test__/identity/mail', {
      params: { email: fixture.invited_email, kind: 'verification' },
    })).json()

    await recipient.goto(verification.url)
    await recipient.getByLabel('Create password').fill('Fixture password 123!')
    await recipient.getByLabel('Confirm password').fill('Fixture password 123!')
    await recipient.getByRole('button', { name: 'Verify email and create account' }).click()
    await expect(recipient.getByRole('heading', { name: 'Email verified' })).toBeVisible()
    await recipient.getByRole('link', { name: 'Sign in to WebHDP' }).click()
    await recipient.getByTestId('login-email').fill(fixture.invited_email)
    await recipient.getByTestId('login-password').fill('Fixture password 123!')
    await recipient.getByTestId('login-submit').click()
    await expect(recipient.getByText('Join ' + name + ' as reader.')).toBeVisible()
    await recipient.getByRole('button', { name: 'Accept invitation' }).click()
    await expect(recipient.getByRole('status').filter({ hasText: 'You joined ' + name + ' as reader.' })).toBeVisible()
    await recipient.getByRole('link', { name: 'Open institution workspace' }).click()
    await expect(recipient.getByRole('heading', { name, exact: true })).toBeVisible()
    await expect(recipient.getByRole('button', { name: 'Send invitation' })).toHaveCount(0)
  } finally {
    await context.close()
  }
})

test('workspace requests are private until reviewed and approval grants ownership', async ({ page, browser, request }) => {
  const fixture = await (await request.post(backend + '/__test__/identity/fixture')).json()
  const name = 'Research Library ' + crypto.randomUUID().slice(0, 8)
  await openWorkspace(page, fixture.requester_token)
  await page.getByRole('textbox', { name: 'Institution name' }).fill(name)
  await page.getByRole('textbox', { name: 'What will the workspace be used for?' }).fill('Shared cataloguing')
  await page.getByRole('button', { name: 'Submit request' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Workspace request sent for review.' })).toBeVisible()

  const context = await browser.newContext()
  try {
    const admin = await context.newPage()
    await openWorkspace(admin, fixture.admin_token)
    await admin.getByRole('button', { name: 'Approve ' + name }).click()
    await expect(admin.getByText('Workspace approved. The requester is its owner.')).toBeVisible()

    await page.getByRole('button', { name: 'Refresh requests' }).click()
    await page.getByRole('link', { name: 'Open workspace' }).click()
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
    await expect(page.getByText('owner role', { exact: true })).toBeVisible()
  } finally {
    await context.close()
  }
})
