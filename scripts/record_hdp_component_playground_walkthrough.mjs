#!/usr/bin/env node
import { execFileSync } from 'node:child_process'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const CLONE_ROOT = process.env.WEBHDP_RECORDING_CLONE_ROOT || '/tmp/webhdp-clone-docker-test'
const BASE_URL = process.env.WEBHDP_RECORDING_BASE_URL || 'http://127.0.0.1:18088'
const COMPOSE = ['compose', '-p', 'webhdp-clone-test', '-f', 'docker-compose.yml', '-f', 'docker-compose.dev.yml']
const VIDEO_ID = 'webhdp_real_01_hdp_component_playground_tests'
const RAW_DIR = path.join(ROOT, 'docs', 'assets', 'screen_recordings', 'raw')
const SUBTITLE_DIR = path.join(ROOT, 'docs', 'assets', 'screen_recordings', 'subtitles')
const MANIFEST_PATH = path.join(ROOT, 'docs', 'assets', 'screen_recordings', 'manifest.json')
const GUIDE_PATH = path.join(ROOT, 'docs', 'guides', 'video_guides', 'components_and_development.md')

function dockerExecPython(source) {
  return execFileSync(
    'docker',
    [...COMPOSE, 'exec', '-T', 'backend', 'python', '-c', source],
    { cwd: CLONE_ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] },
  ).trim().split(/\n/).pop()
}

function recordingAdminToken() {
  return dockerExecPython(`from app import app
from database.models import User
from routes.auth_routes import _create_access_token_for_user
with app.app_context():
    user = User.query.filter_by(email="recording-admin@example.test").first() or User.query.filter_by(email="alpha-admin@example.test").first()
    print(_create_access_token_for_user(user))
`)
}

function ensurePlaygroundFixture() {
  return JSON.parse(dockerExecPython(`from app import app
from database.database import db
from database.models import User, Session, File
from pathlib import Path
import json, shutil
with app.app_context():
    user = User.query.filter_by(email="recording-admin@example.test").first() or User.query.first()
    root = Path("/shared/sessions/recording-playground-session")
    source = root / "source_files"
    source.mkdir(parents=True, exist_ok=True)
    src = Path("/app/test_data/workflow_fixtures/cases/root_stem_mixed/bronze_helmet.glb")
    dst = source / "bronze_helmet.glb"
    shutil.copyfile(src, dst)
    session = Session.query.filter_by(session_dir=str(root)).first()
    if not session:
        session = Session(user_id=user.id, session_dir=str(root), status="scanned", origin_type="workflow", access_mode="full")
        db.session.add(session)
        db.session.flush()
    session.status = "scanned"
    file_row = File.query.filter_by(session_id=session.id, filename="bronze_helmet.glb").first()
    if not file_row:
        file_row = File(session_id=session.id, filename="bronze_helmet.glb", path=str(dst), size=dst.stat().st_size, status="uploaded")
        db.session.add(file_row)
    else:
        file_row.path = str(dst)
        file_row.size = dst.stat().st_size
        file_row.status = "uploaded"
    db.session.commit()
    print(json.dumps({"session_id": session.id, "path": "source_files/bronze_helmet.glb"}))
`))
}

async function ensureDirs() {
  await fs.mkdir(RAW_DIR, { recursive: true })
  await fs.mkdir(SUBTITLE_DIR, { recursive: true })
  await fs.mkdir(path.dirname(GUIDE_PATH), { recursive: true })
}

async function writeSubtitles() {
  const subtitles = `WEBVTT

00:00:00.000 --> 00:00:05.000
Open the HDP Component Playground in a local Docker WebHDP instance.

00:00:05.000 --> 00:00:10.000
Filter the manifest-backed components and open Input File Classification.

00:00:10.000 --> 00:00:16.000
Select a seeded test session and a session-relative GLB fixture.

00:00:16.000 --> 00:00:21.000
Run the component through the Playground form without exposing credentials.

00:00:21.000 --> 00:00:27.000
Review the completed run and classification JSON to confirm the component test passed.
`
  await fs.writeFile(path.join(SUBTITLE_DIR, `${VIDEO_ID}.en.vtt`), subtitles, 'utf8')
}

async function writeManifestAndGuide() {
  const entry = {
    id: VIDEO_ID,
    title: 'HDP Component Playground And Component Tests',
    kind: 'real-alpha-recording',
    source_document: 'docs/guides/video_guides/components_and_development.md',
    webm: `docs/assets/screen_recordings/raw/${VIDEO_ID}.webm`,
    video: `docs/assets/screen_recordings/raw/${VIDEO_ID}.mp4`,
    subtitles: `docs/assets/screen_recordings/subtitles/${VIDEO_ID}.en.vtt`,
  }
  const manifest = {
    version: 1,
    updated: '2026-05-29',
    entries: [entry],
  }
  await fs.writeFile(MANIFEST_PATH, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')

  const guide = `# Release Walkthrough Videos

This page contains accepted alpha release walkthrough recordings. Each accepted
video must show a real, replayable workflow against a local WebHDP Docker
instance. Generated route tours and caption-only placeholders are not accepted.

## Accepted Recordings

### HDP Component Playground And Component Tests

Purpose: show how to open the HDP Component Playground, select a manifest-backed
component, run it against a session-backed fixture, and verify the component test
result from the completed Playground output.

<video controls muted playsinline preload="metadata">
  <source src="/api/v1/docs/assets/screen_recordings/raw/${VIDEO_ID}.webm" type="video/webm">
  <source src="/api/v1/docs/assets/screen_recordings/raw/${VIDEO_ID}.mp4" type="video/mp4">
  <track kind="subtitles" src="/api/v1/docs/assets/screen_recordings/subtitles/${VIDEO_ID}.en.vtt" srclang="en" label="English">
  Your browser does not support the embedded video.
</video>

Workflow evidence shown in the video:

1. The Playground lists manifest-backed HDP Components from the running instance.
2. The user opens Input File Classification from the component catalog.
3. The run uses a seeded session fixture at \`source_files/bronze_helmet.glb\`.
4. The Playground run completes successfully.
5. The result JSON classifies the GLB as a 3D mesh model.

## Additional Recordings

Add new component recordings only after they show a complete, repeatable
component workflow and avoid credentials, private endpoints, and personal
filesystem paths.
`
  await fs.writeFile(GUIDE_PATH, guide, 'utf8')
}

async function recordPlayground() {
  const { chromium } = await import(path.join(ROOT, 'frontend', 'node_modules', 'playwright', 'index.mjs'))
  const fixture = ensurePlaygroundFixture()
  const token = recordingAdminToken()
  const tempVideoDir = path.join(ROOT, '.tmp-recordings')
  await fs.rm(tempVideoDir, { recursive: true, force: true })
  await fs.mkdir(tempVideoDir, { recursive: true })

  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    recordVideo: { dir: tempVideoDir, size: { width: 1440, height: 900 } },
  })
  await context.addInitScript((authToken) => {
    window.sessionStorage.setItem('token', authToken)
  }, token)

  const page = await context.newPage()
  await page.goto(`${BASE_URL}/tools/playground`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(3200)
  await page.getByRole('button', { name: 'OK' }).click({ timeout: 1500 }).catch(() => {})

  const filter = page.getByPlaceholder('Filter components')
  await filter.fill('classification')
  await page.waitForTimeout(2500)
  await page.getByText('Input File Classification').scrollIntoViewIfNeeded()
  await page.waitForTimeout(1400)
  await page.getByRole('button', { name: 'Open' }).last().click()
  await page.waitForTimeout(2600)

  await page.locator('select').nth(2).selectOption(String(fixture.session_id))
  await page.waitForTimeout(2200)
  await page.locator('input[type="text"]').fill(fixture.path)
  await page.waitForTimeout(3600)

  await page.getByRole('button', { name: 'Run Playground' }).click()
  await page.waitForTimeout(3400)
  await page.getByText('Classification JSON').scrollIntoViewIfNeeded()
  await page.waitForTimeout(8200)

  const bodyText = await page.locator('body').innerText()
  if (!/Run [0-9a-f-]{36}/.test(bodyText) || !bodyText.includes('completed') || !/"is_3d_model"\s*:\s*true/.test(bodyText)) {
    await fs.writeFile(path.join(ROOT, '.tmp-recordings', `${VIDEO_ID}.failure.txt`), bodyText, 'utf8')
    await page.screenshot({ path: path.join(ROOT, '.tmp-recordings', `${VIDEO_ID}.failure.png`), fullPage: true })
    throw new Error('Playground recording did not reach a completed component-test result.')
  }
  if (bodyText.includes('404')) {
    await fs.writeFile(path.join(ROOT, '.tmp-recordings', `${VIDEO_ID}.failure.txt`), bodyText, 'utf8')
    await page.screenshot({ path: path.join(ROOT, '.tmp-recordings', `${VIDEO_ID}.failure.png`), fullPage: true })
    throw new Error('Playground recording still shows a 404 preview/download error.')
  }

  await context.close()
  await browser.close()

  const files = await fs.readdir(tempVideoDir)
  const recordedWebm = files.find((name) => name.endsWith('.webm'))
  if (!recordedWebm) {
    throw new Error('Playwright did not produce a WebM recording.')
  }
  const webmPath = path.join(RAW_DIR, `${VIDEO_ID}.webm`)
  const mp4Path = path.join(RAW_DIR, `${VIDEO_ID}.mp4`)
  await fs.copyFile(path.join(tempVideoDir, recordedWebm), webmPath)
  execFileSync('ffmpeg', [
    '-hide_banner',
    '-loglevel',
    'error',
    '-y',
    '-i',
    webmPath,
    '-vf',
    'scale=1280:-2',
    '-c:v',
    'libx264',
    '-pix_fmt',
    'yuv420p',
    '-movflags',
    '+faststart',
    mp4Path,
  ], { stdio: 'inherit' })
  await fs.rm(tempVideoDir, { recursive: true, force: true })
}

await ensureDirs()
await recordPlayground()
await writeSubtitles()
await writeManifestAndGuide()
console.log(`Recorded ${VIDEO_ID}`)
