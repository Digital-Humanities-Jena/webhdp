/** Operator-provided copy is always text; result links come from a fixed origin. */
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

export function applyPresentation(document, config) {
  for (const [field, selector] of [['hero_title', '.hero h1'], ['hero_description', '.hero p'], ['scope_note', '.scope-note']]) {
    if (typeof config[field] === 'string' && config[field].trim()) {
      const element = document.querySelector(selector)
      if (element) element.textContent = config[field]
    }
  }
  const note = document.getElementById('upload-note')
  if (note) note.textContent = 'Source files go to your selected WebHDP instance. Its pipeline may transfer them to the services described here. This application has no connection to the HPC.'
}

export function sandboxReceiptSummary(receipt) {
  if (!receipt || receipt.operation !== 'zenodo-sandbox-draft' || receipt.environment !== 'sandbox' || receipt.submitted !== false || receipt.publication_attempted !== false || receipt.publication_status !== 'unpublished_draft' || !Number.isSafeInteger(receipt.deposition_id) || receipt.deposition_id < 1 || !Array.isArray(receipt.files) || receipt.files.length === 0) {
    throw new Error('The Sandbox receipt does not describe a verified unpublished draft.')
  }
  if (!receipt.files.every(file => typeof file.name === 'string' && Number.isSafeInteger(file.size) && file.size > 0 && /^[a-f0-9]{64}$/.test(file.sha256))) throw new Error('The Sandbox receipt has invalid file verification data.')
  return { id: receipt.deposition_id, url: `https://sandbox.zenodo.org/uploads/${receipt.deposition_id}`, files: receipt.files.length }
}

export function renderSandboxReceipt(document, container, receipt) {
  const summary = sandboxReceiptSummary(receipt)
  const card = document.createElement('div'); card.className = 'message sandbox-receipt'
  const title = document.createElement('strong'); title.textContent = `Unpublished Sandbox draft #${summary.id}`
  const detail = document.createElement('p'); detail.textContent = `${summary.files} files uploaded and downloaded again for size and SHA-256 verification. This is a test draft; nothing was published.`
  const link = document.createElement('a'); link.href = summary.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = 'Open draft in Zenodo Sandbox ↗'
  const hint = document.createElement('p'); hint.className = 'hint'; hint.textContent = 'Sign in to the Sandbox account that owns the configured credential to view the draft.'
  card.append(title, detail, link, hint); container.append(card)
}
