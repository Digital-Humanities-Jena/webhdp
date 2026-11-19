import { WebHdpLink } from '/sdk/client.mjs'
import { loadDatasetFiles, renderDatasetCard } from './datasets.mjs'
import { applyPresentation, renderSandboxReceipt, linkProgressPhase } from './presentation.mjs'
const $ = id => document.getElementById(id)
const app = document.body.dataset.app
const config = await fetch('/config.json', { cache: 'no-store' }).then(r => {
  if (!r.ok) throw new Error('Start the prototype with the demo launcher to load its instance configuration.')
  return r.json()
}).catch(error => { $('message').hidden = false; $('message').textContent = error.message; throw error })
applyPresentation(document, config)
const link = new WebHdpLink({ baseUrl: config.base_url, clientId: config.client_id })
let pipeline, selectedFiles = [], activeRun, polling, objectUrls = [], submitting = false
let datasetSelection, loadingDataset
const datasetButtons = new Map()
const datasetStorageKey = `webhdp-link:dataset:${config.client_id}`
function message(text, error = false) { $('message').hidden = !text; $('message').textContent = text; $('message').classList.toggle('error', error) }
function reportError(error) {
  if (error?.status === 401) {
    // Expiry ends this browser connection; revoking its grant would also stop
    // already accepted jobs. Keep that server authorization intact.
    polling?.abort(); link.accessToken = null; pipeline = null; updateConnection()
    message('Your connection expired. Connect with WebHDP again, then select the job under Your recent jobs to resume tracking. Accepted jobs continue processing.', true)
    return
  }
  message(error.message, true)
}
function setFiles(files) {
  selectedFiles = [...files]; $('file-list').replaceChildren()
  for (const file of selectedFiles) { const li = document.createElement('li'); li.textContent = `${file.name} · ${(file.size / 1024).toFixed(1)} KB`; $('file-list').append(li) }
}
function showDatasetSelection() {
  for (const [id, button] of datasetButtons) {
    const selected = id === datasetSelection?.id
    button.setAttribute('aria-pressed', String(selected))
    button.textContent = selected ? 'Loaded' : 'Load dataset'
    button.disabled = submitting || !!loadingDataset
  }
  const status = $('dataset-status')
  if (status) {
    status.textContent = loadingDataset
      ? `Loading ${loadingDataset.dataset.title}…`
      : datasetSelection
        ? `${datasetSelection.title} loaded · ${selectedFiles.length} ${selectedFiles.length === 1 ? 'file' : 'files'}`
        : ''
  }
}
async function selectDataset(dataset) {
  loadingDataset?.controller.abort()
  const request = { dataset, controller: new AbortController() }
  loadingDataset = request
  updateConnection()
  try {
    const files = await loadDatasetFiles(dataset.files, request.controller.signal)
    if (loadingDataset !== request) return
    $('files').value = ''
    setFiles(files)
    datasetSelection = dataset
    sessionStorage.setItem(datasetStorageKey, dataset.id)
    message('')
  } catch (error) {
    if (!request.controller.signal.aborted) message(error.message, true)
  } finally {
    if (loadingDataset === request) {
      loadingDataset = null
      updateConnection()
    }
  }
}
function updateConnection() {
  const connected = !!link.accessToken
  $('connection-status').classList.toggle('connected', connected)
  $('connection-status').replaceChildren(Object.assign(document.createElement('i'), { className: 'dot' }), document.createTextNode(connected ? 'Connected to WebHDP' : 'WebHDP not connected'))
  $('connect').textContent = connected ? 'Disconnect' : 'Connect with WebHDP'
  $('run').disabled = !connected || !pipeline || submitting || !!loadingDataset
  $('files').disabled = submitting
  $('cancel').disabled = !connected
  for (const button of $('recent-list').querySelectorAll('button')) button.disabled = !connected
  showDatasetSelection()
}
function parameterSchema() { return pipeline.parameters_schema || pipeline.parameter_schema || pipeline.parameters || { properties: {} } }
function renderPipeline() {
  $('pipeline-name').textContent = `${pipeline.name} · ${pipeline.pipeline_version || pipeline.version || '1.0.0'}`
  const structure = pipeline.structure || pipeline.steps || []
  if (structure.length) $('pipeline-flow').textContent = structure.map(step => step.name || step.label || step.id).join(' → ')
  const input = pipeline.input || pipeline.inputs || {}
  $('files').accept = (input.extensions || []).join(',')
  $('files').multiple = input.max_files !== 1
  const minFiles = input.min_files || 1
  const maxFiles = input.max_files || 1
  const fileCount = minFiles === maxFiles ? String(minFiles) : `${minFiles}–${maxFiles}`
  $('file-hint').textContent = `${(input.extensions || []).join(', ').toUpperCase()} · ${fileCount} ${maxFiles === 1 ? 'file' : 'files'} per job`
  $('batch-label').hidden = app === 'photo-lab'
  const schema = parameterSchema(); $('parameters').replaceChildren()
  for (const [name, def] of Object.entries(schema.properties || {})) {
    const row = document.createElement('div'); row.className = 'field'
    const label = document.createElement('label'); label.htmlFor = `param-${name}`; label.textContent = def.title || def.label || name.replaceAll('_', ' ')
    const input = document.createElement(def.enum ? 'select' : 'input'); input.id = label.htmlFor; input.name = name
    if (def.enum) for (const value of def.enum) input.append(Object.assign(document.createElement('option'), { value: String(value), textContent: String(value) }))
    else input.type = ['number', 'integer'].includes(def.type) ? 'number' : def.type === 'boolean' ? 'checkbox' : 'text'
    if (def.type === 'number') input.step = 'any'
    if (def.minimum !== undefined) input.min = def.minimum
    if (def.maximum !== undefined) input.max = def.maximum
    if (def.maxLength !== undefined) input.maxLength = def.maxLength
    input.required = (schema.required || []).includes(name)
    if (def.type === 'boolean') input.checked = !!def.default
    else if (def.default !== undefined) input.value = String(def.default)
    row.append(label, input)
    if (def.description) row.append(Object.assign(document.createElement('small'), { className: 'hint', textContent: def.description }))
    $('parameters').append(row)
  }
}
async function connect() {
  if (link.accessToken) {
    polling?.abort(); await link.disconnect(); pipeline = null; updateConnection(); message('Disconnected from WebHDP.'); return
  }
  location.assign(await link.authorizationUrl({ redirectUri: `${location.origin}/${app}/` }))
}
async function load() {
  const data = await link.pipeline(config.pipeline_id); pipeline = data.pipeline || data
  renderPipeline(); updateConnection(); await recent()
}
async function recent() {
  const data = await link.runs(); const runs = Array.isArray(data) ? data : data.runs || data.items || []
  $('recent').hidden = !runs.length; $('recent-list').replaceChildren()
  for (const run of runs.slice(0, 8)) {
    const button = document.createElement('button'); button.className = 'secondary'; button.textContent = `${run.id.slice(0, 8)} · ${linkProgressPhase(run)?.label || run.status}`
    button.addEventListener('click', () => monitor(run).catch(reportError)); $('recent-list').append(button)
  }
}
function showRun(run) {
  activeRun = run; $('hosted-link').hidden = !run.progress_url; if (run.progress_url) $('hosted-link').href = link.hostedUrl(run); $('empty').hidden = true; $('results').hidden = false
  $('status').textContent = run.status[0].toUpperCase() + run.status.slice(1); $('status').dataset.state = run.status
  const progress = run.progress || {}; const complete = run.status === 'succeeded'
  $('progress').style.width = `${complete ? 100 : (progress.completed || 0) / Math.max(progress.total || 1, 1) * 100}%`
  $('run-meta').replaceChildren()
  const phase = linkProgressPhase(run)
  if (phase) {
    const note = document.createElement('div'); note.className = 'phase-note'; note.setAttribute('role', 'status'); note.setAttribute('aria-live', 'polite')
    note.append(Object.assign(document.createElement('strong'), { textContent: phase.label }), Object.assign(document.createElement('p'), { textContent: phase.detail }))
    $('run-meta').append(note)
  }
  for (const text of [`Job ${run.id}`, `Pipeline ${run.pipeline_id} · version ${run.pipeline_version || '1.0.0'}`, ...(run.steps || []).map(step => `${step.name || step.id}: ${step.status}`)]) {
    $('run-meta').append(Object.assign(document.createElement('div'), { textContent: text }))
  }
  $('cancel').hidden = !['queued', 'running'].includes(run.status)
  if (run.error) message(typeof run.error === 'string' ? run.error : run.error.detail || 'Processing failed. Review the source and try a new job.', true)
  $('artifacts').replaceChildren()
  for (const artifact of run.artifacts || []) {
    const row = document.createElement('div'); row.className = 'artifact'
    const description = document.createElement('div'); description.append(Object.assign(document.createElement('strong'), { textContent: artifact.name }), Object.assign(document.createElement('small'), { textContent: `${((artifact.size || 0) / 1024).toFixed(1)} KB · SHA-256 ${artifact.sha256?.slice(0, 12) || 'available'}…` }))
    const button = document.createElement('button'); button.className = 'secondary'; button.textContent = 'Download'
    button.onclick = async () => {
      button.disabled = true
      try { const blob = await link.download(run.id, artifact); const url = URL.createObjectURL(blob); objectUrls.push(url); const a = document.createElement('a'); a.href = url; a.download = artifact.name; a.click(); message(`${artifact.name}: download verified against SHA-256.`) }
      catch (error) { reportError(error) } finally { button.disabled = !link.accessToken }
    }
    row.append(description, button); $('artifacts').append(row)
  }
}
async function monitor(run) {
  polling?.abort(); const controller = new AbortController(); polling = controller; $('preview').replaceChildren(); showRun(run)
  try {
    const final = await link.wait(run.id, { signal: controller.signal, interval: config.poll_interval_ms || 700, onProgress: showRun })
    if (final.status === 'succeeded') {
      message(`Processing complete. ${final.artifacts.length} output(s) are ready for verified download.`)
      const receipt = final.artifacts.find(item => item.name === 'zenodo-sandbox-receipt.json')
      if (receipt) {
        if (receipt.size > 1024 * 1024) throw new Error('The Sandbox receipt is unexpectedly large.')
        const blob = await link.download(final.id, receipt)
        const value = JSON.parse(await blob.text())
        if (controller.signal.aborted) return
        renderSandboxReceipt(document, $('preview'), value)
      }
      const preview = final.artifacts.find(item => /^image\/(png|jpeg|webp)$/.test(item.media_type))
      if (preview) { const blob = await link.download(final.id, preview); if (controller.signal.aborted) return; const url = URL.createObjectURL(blob); objectUrls.push(url); $('preview').append(Object.assign(document.createElement('img'), { className: 'artifact-preview', src: url, alt: 'Pipeline output preview' })) }
    }
    await recent()
  } catch (error) {
    if (!controller.signal.aborted) {
      if (error?.status === 401) reportError(error)
      else throw error
    }
  }
}
async function submit() {
  if (!selectedFiles.length) throw new Error('Choose source files or use the sample data first.')
  if (!$('parameters').reportValidity()) return
  submitting = true; updateConnection(); message('Uploading source files to WebHDP…')
  try {
    const parameters = {}
    for (const [name, def] of Object.entries(parameterSchema().properties || {})) {
      const input = $(`param-${name}`)
      if (input.type !== 'checkbox' && input.value === '') continue
      parameters[name] = def.type === 'boolean' ? input.checked : ['number', 'integer'].includes(def.type) ? Number(input.value) : input.value
    }
    const uploads = []
    for (const file of selectedFiles) uploads.push(await link.upload(file))
    const groups = $('batch').checked ? uploads.map(upload => [upload]) : [uploads]
    const runs = []
    for (const inputs of groups) runs.push(await link.submit({ pipelineId: config.pipeline_id, inputs, parameters }))
    if ($('hosted').checked && runs[0].progress_url) { location.assign(link.hostedUrl(runs[0])); return }
    message(`${runs.length} job(s) accepted by WebHDP. Queued work continues if you close this page.`)
    await recent(); await monitor(runs[0])
  } finally { submitting = false; updateConnection() }
}
$('connect').onclick = () => connect().catch(reportError)
$('files').onchange = event => {
  loadingDataset?.controller.abort()
  loadingDataset = null
  datasetSelection = null
  sessionStorage.removeItem(datasetStorageKey)
  setFiles(event.target.files)
  updateConnection()
}
$('run').onclick = () => submit().catch(error => { reportError(error); updateConnection() })
$('cancel').onclick = async () => { try { showRun(await link.cancel(activeRun.id)); message('Cancellation requested; a running step may finish before the job stops.') } catch (error) { reportError(error) } }
const sampleButton = $('sample')
sampleButton.hidden = !config.samples?.length
sampleButton.onclick = async () => {
  try {
    const files = await loadDatasetFiles(config.samples)
    setFiles(files); message('Sample data selected. You can adjust the parameters before submitting.')
  } catch (error) { message(error.message, true) }
}
if ($('datasets') && config.datasets?.length) {
  sampleButton.hidden = true
  for (const dataset of config.datasets) {
    const { card, button } = renderDatasetCard(dataset, selectDataset)
    datasetButtons.set(dataset.id, button)
    $('dataset-list').append(card)
  }
  $('datasets').hidden = false
  const savedDataset = config.datasets.find(dataset => dataset.id === sessionStorage.getItem(datasetStorageKey))
  if (savedDataset) void selectDataset(savedDataset)
}
$('api-docs').href = `${config.base_url}/openapi.json`
window.addEventListener('pagehide', () => { polling?.abort(); loadingDataset?.controller.abort(); objectUrls.forEach(url => URL.revokeObjectURL(url)) })
try { if (await link.completeAuthorization()) { message('Connection approved. Only this application’s permitted pipelines and jobs are available.'); await load() } } catch (error) { reportError(error) }
updateConnection()
