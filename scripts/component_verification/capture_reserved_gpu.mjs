/** Verify a non-admin's real WebHDP reservation and run in the isolated browser rehearsal. */
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const require = createRequire(path.join(root, 'frontend/package.json'))
const { chromium, expect } = require('@playwright/test')
const { values, positionals: [phase] } = parseArgs({
  allowPositionals: true,
  options: {
    frontend: { type: 'string' }, credentials: { type: 'string' }, output: { type: 'string' },
    'session-id': { type: 'string' }, 'reservation-id': { type: 'string' }, 'job-id': { type: 'string' },
    node: { type: 'string' }, 'run-receipt': { type: 'string' },
  },
})
assert(['claim', 'finish'].includes(phase), 'Choose claim or finish')
for (const key of ['frontend', 'credentials', 'output', 'session-id', 'reservation-id', 'job-id', 'node']) {
  assert(values[key], `Missing --${key}`)
}
const frontend = new URL(values.frontend)
assert(['127.0.0.1', 'localhost'].includes(frontend.hostname) && ['http:', 'https:'].includes(frontend.protocol), 'Use the isolated loopback WebHDP frontend')
const sessionId = Number(values['session-id'])
assert(Number.isSafeInteger(sessionId) && sessionId > 0, 'Invalid uploaded session ID')
const reservationId = values['reservation-id']
const jobId = values['job-id']
const node = values.node
const credentials = JSON.parse(await readFile(values.credentials, 'utf8'))
const output = path.resolve(values.output)
await mkdir(output, { recursive: true })

const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1560, height: 1060 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))

const apiResponse = (endpoint, method = 'GET') => page.waitForResponse(response => (
  new URL(response.url()).pathname === endpoint && response.request().method() === method
), { timeout: 60000 })

async function responseData(responsePromise) {
  const response = await responsePromise
  const payload = await response.json()
  assert(response.ok(), `${response.request().method()} ${new URL(response.url()).pathname} returned ${response.status()}: ${payload.error?.message || 'request failed'}`)
  return payload.data
}

async function login() {
  await page.goto(new URL('/login', frontend).href)
  await page.getByTestId('login-email').fill(credentials.email)
  await page.getByTestId('login-password').fill(credentials.password)
  const loginResponse = apiResponse('/api/v1/auth/login', 'POST')
  await page.getByTestId('login-submit').click()
  const data = await responseData(loginResponse)
  assert(data.user && data.user.role && data.user.role !== 'admin', 'Rehearse the allowed non-admin account')
  await page.waitForURL(url => url.pathname !== '/login')
  const cookieNotice = page.getByRole('button', { name: 'OK', exact: true })
  if (await cookieNotice.isVisible()) await cookieNotice.click()
  return data.user.role
}

async function openReservation() {
  const list = apiResponse('/api/v1/hpc-link/reservations')
  await page.goto(new URL('/hpc-resources', frontend).href)
  const data = await responseData(list)
  const reservation = data.reservations.find(item => item.reservation_id === reservationId)
  assert(reservation && String(reservation.job_id) === jobId && reservation.node_name === node, 'Browser did not receive the expected reservation')
  const region = page.getByTestId('reserved-gpu-access')
  const card = region.getByTestId(`reserved-gpu-card-${reservationId}`)
  await expect(card).toHaveCount(1)
  await expect(card).toContainText(node)
  await region.getByTestId('reserved-gpu-session').selectOption(String(sessionId))
  return { reservation, card, region }
}

function allocationFacts(allocation) {
  assert.equal(allocation.session_id, sessionId)
  assert.equal(allocation.reservation_id, reservationId)
  assert.equal(String(allocation.remote_job_id), jobId)
  assert.equal(allocation.node_name, node)
  return {
    allocation_id: allocation.allocation_id, reservation_id: allocation.reservation_id,
    session_id: allocation.session_id, job_id: String(allocation.remote_job_id),
    node: allocation.node_name, status: allocation.status,
  }
}

async function captureClaim() {
  const { reservation, card } = await openReservation()
  assert(reservation.can_claim === true && reservation.status === 'available', 'Reservation must be available before the browser claim')
  const response = apiResponse(`/api/v1/hpc-link/reservations/${reservationId}/claim`, 'POST')
  await card.getByRole('button', { name: 'Use reserved GPU', exact: true }).click()
  const allocation = allocationFacts((await responseData(response)).allocation)
  assert.equal(allocation.status, 'running', 'Browser claim did not confirm the GPU session')
  await expect(card).toContainText('Ready for this session')
  await expect(card.getByRole('button', { name: 'Release access', exact: true })).toBeEnabled()
  await page.screenshot({ path: path.join(output, 'reserved-gpu-claimed.png'), animations: 'disabled', fullPage: true })
  return { ...allocation, expires_at: reservation.expires_at }
}

async function captureRun() {
  assert(values['run-receipt'], 'Finish requires --run-receipt')
  const receipt = JSON.parse(await readFile(values['run-receipt'], 'utf8'))
  const run = receipt.run
  assert(run?.run_id && run.status === 'completed' && run.steps?.length, 'Use a real completed pipeline receipt')
  assert.equal(run.session_id, sessionId, 'Pipeline run does not belong to the claimed upload session')
  const runId = run.run_id
  const savedRunResponse = apiResponse(`/api/v2/runs/${runId}`)
  await page.goto(new URL(`/tools/pipeline-constructor?run=${encodeURIComponent(runId)}`, frontend).href)
  const savedRun = (await responseData(savedRunResponse)).run
  assert.equal(savedRun.status, 'completed')
  assert.equal(savedRun.session_id, sessionId)
  assert.deepEqual(savedRun.steps.map(step => [step.component_key, step.status]), run.steps.map(step => [step.component_key, step.status]))
  await expect(page.getByRole('link', { name: `Open saved run ${runId}` })).toBeVisible({ timeout: 60000 })
  for (const step of savedRun.steps) {
    await expect(page.getByTestId(`execution-step-${step.pipeline_step_id}`)).toContainText('completed')
  }
  const report = (receipt.artifact_download_checks || []).find(item => item.name?.endsWith('.json') && item.sha256)
  assert(report, 'Use a receipt that contains a verified JSON artifact SHA-256')
  const artifact = page.getByRole('button', { name: `Download ${report.name}`, exact: true })
  await expect(artifact).toBeVisible()
  await artifact.scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(output, 'reserved-gpu-completed-run.png'), animations: 'disabled' })
  const download = page.waitForEvent('download')
  await artifact.click()
  const destination = path.join(output, `browser-${path.basename(report.name)}`)
  await (await download).saveAs(destination)
  const sha256 = createHash('sha256').update(await readFile(destination)).digest('hex')
  assert.equal(sha256, report.sha256, 'Browser download did not match the independently checked API artifact')
  return { run_id: runId, steps_completed: run.steps.length, artifact: report.name, artifact_sha256: sha256 }
}

async function captureRelease() {
  const { reservation, card, region } = await openReservation()
  const allocation = allocationFacts(reservation.allocation)
  const release = apiResponse(`/api/v1/hpc-link/allocations/${allocation.allocation_id}/release`, 'POST')
  await card.getByRole('button', { name: 'Release access', exact: true }).click()
  const data = await responseData(release)
  assert.equal(data.allocation.status, 'released')
  assert.equal(data.remote.detached, true)
  assert.equal(data.remote.cancelled, false)
  await expect(region.getByRole('status')).toContainText('Access released')
  await expect(card.getByRole('button', { name: 'Use reserved GPU', exact: true })).toBeEnabled()
  await page.screenshot({ path: path.join(output, 'reserved-gpu-released.png'), animations: 'disabled', fullPage: true })
  return { allocation_id: allocation.allocation_id, detached: true, cancelled: false }
}

try {
  const role = await login()
  const evidence = phase === 'claim'
    ? { claim: await captureClaim() }
    : { run: await captureRun(), release: await captureRelease() }
  assert.deepEqual(errors, [], 'Browser emitted application errors')
  const record = { ...evidence, role, recorded_at: new Date().toISOString(), mocked_responses: false, errors }
  await writeFile(path.join(output, `reserved-gpu-browser-${phase}.json`), JSON.stringify(record, null, 2) + '\n')
  console.log(JSON.stringify(evidence))
} finally {
  await browser.close()
}
