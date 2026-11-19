export const linkScopeLabels = {
  'pipelines:read': 'View the pipelines available to this application',
  'uploads:write': 'Upload input files to WebHDP',
  'runs:write': 'Submit and cancel processing jobs',
  'runs:read': 'Read job status and processing results',
  'artifacts:read': 'Download output files',
}

export function linkErrorMessage(error) {
  return error?.detail || error?.error?.message || error?.message || 'The request could not be completed. Please try again.'
}

export function linkProgressPhase(run) {
  if (!['queued', 'running'].includes(run?.status)) return null
  const phase = run.status === 'queued' ? 'queued' : run.progress?.phase
  const phases = {
    queued: { label: 'In processing queue', detail: 'WebHDP has accepted this job. It will start when a worker is available.' },
    waiting_for_resources: { label: 'Waiting for resources', detail: 'WebHDP is waiting for computing resources. Processing will start when they are available. You can leave this page and return later.' },
    processing: { label: 'Processing', detail: 'The pipeline is processing your files.' },
    finalizing: { label: 'Preparing results', detail: 'WebHDP is collecting results and settling the final job status.' },
  }
  return Object.hasOwn(phases, phase) ? phases[phase] : { label: 'Job in progress', detail: 'WebHDP is managing this job. Detailed processing phase is not available.' }
}

export function linkLoginDestination(value, fallback = '/workflow/upload') {
  // Resume only known workflow pages. Never accept an external URL.
  if (typeof value !== 'string' || /[\\\r\n]/.test(value)) return fallback
  try {
    const destination = new URL(value, 'https://webhdp.invalid')
    const allowed = ['/model-publication', '/onboarding', '/tutorial/3d', '/institution-invitation', '/account/setup'].includes(destination.pathname)
      || (destination.pathname === '/link/authorize' && value.startsWith('/link/authorize?'))
      || /^\/link\/jobs(?:\/[A-Za-z0-9_-]{1,80})?$/.test(destination.pathname)
    if (destination.origin === 'https://webhdp.invalid' && value.startsWith('/') && allowed) {
      return destination.pathname + destination.search
    }
  } catch { /* Fall through to the standard signed-in destination. */ }
  return fallback
}

export function authorizationParameters(query) {
  const fields = ['client_id', 'redirect_uri', 'response_type', 'code_challenge', 'code_challenge_method', 'state', 'scope']
  return Object.fromEntries(fields.map((field) => [field, typeof query[field] === 'string' ? query[field] : '']))
}

export function navigateLinkCallback(destination, registeredRedirect) {
  const target = new URL(destination)
  const registered = new URL(registeredRedirect)
  if (!['http:', 'https:'].includes(target.protocol) || target.username || target.password ||
      target.origin !== registered.origin || target.pathname !== registered.pathname || target.hash !== registered.hash) {
    throw new Error('WebHDP returned an unexpected application address. Authorization was stopped.')
  }
  for (const [key, value] of registered.searchParams) {
    if (target.searchParams.get(key) !== value) throw new Error('WebHDP returned an unexpected application address.')
  }
  window.location.assign(target.href)
}

export async function verifyLinkArtifact(blob, artifact) {
  if (!blob || !Number.isSafeInteger(artifact?.size) || artifact.size < 0 || blob.size !== artifact.size) {
    throw new Error('The output size does not match the recorded result. Download stopped; refresh and try again.')
  }
  if (!/^[a-fA-F0-9]{64}$/.test(artifact.sha256 || '')) {
    throw new Error('This output has no valid checksum. Download stopped; contact the WebHDP maintainer.')
  }
  if (!globalThis.crypto?.subtle) {
    throw new Error('Your browser cannot verify this output here. Open WebHDP over HTTPS and try again.')
  }
  const digest = await globalThis.crypto.subtle.digest('SHA-256', await blob.arrayBuffer())
  const actual = Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('')
  if (actual !== artifact.sha256.toLowerCase()) {
    throw new Error('The output checksum does not match the recorded result. Download stopped; refresh and try again.')
  }
}

export function isEmbeddedLinkWindow(browserWindow = window) {
  try { return browserWindow.self !== browserWindow.top }
  catch { return true }
}
