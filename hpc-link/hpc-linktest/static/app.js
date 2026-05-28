const state = {
  appId: '',
  sessionId: null,
  schedulerState: 'idle',
  pollTimer: null,
  runtimePollTimer: null,
  runtimeSnapshot: '',
  runtimeLogError: '',
  authToken: '',
};

const AUTH_TOKEN_KEY = 'hpc_link_access_token';

const els = {
  accessToken: document.getElementById('access-token'),
  saveTokenBtn: document.getElementById('save-token-btn'),
  clearTokenBtn: document.getElementById('clear-token-btn'),
  authStatus: document.getElementById('auth-status'),
  appSelect: document.getElementById('app-select'),
  modelSelect: document.getElementById('model-select'),
  partition: document.getElementById('partition'),
  duration: document.getElementById('duration'),
  gpuType: document.getElementById('gpu-type'),
  gpuCount: document.getElementById('gpu-count'),
  allocateBtn: document.getElementById('allocate-btn'),
  releaseBtn: document.getElementById('release-btn'),
  sessionId: document.getElementById('session-id'),
  jobId: document.getElementById('job-id'),
  schedulerState: document.getElementById('scheduler-state'),
  remaining: document.getElementById('remaining'),
  chatWindow: document.getElementById('chat-window'),
  chatForm: document.getElementById('chat-form'),
  chatInput: document.getElementById('chat-input'),
  sendBtn: document.getElementById('send-btn'),
  temperature: document.getElementById('temperature'),
  maxTokens: document.getElementById('max-tokens'),
  logWindow: document.getElementById('log-window'),
  clearLog: document.getElementById('clear-log'),
  runtimeLogWindow: document.getElementById('runtime-log-window'),
  clearRuntimeLog: document.getElementById('clear-runtime-log'),
};

function now() {
  return new Date().toLocaleTimeString('en-US', { hour12: false });
}

function log(level, message) {
  const line = document.createElement('div');
  line.className = `log-line ${level}`;
  line.textContent = `[${now()}] [${level.toUpperCase()}] ${message}`;
  els.logWindow.appendChild(line);
  els.logWindow.scrollTop = els.logWindow.scrollHeight;
}

function addChat(role, text) {
  const line = document.createElement('div');
  line.className = `chat-line ${role}`;

  const roleEl = document.createElement('div');
  roleEl.className = 'chat-role';
  roleEl.textContent = role;

  const textEl = document.createElement('div');
  textEl.className = 'chat-text';
  textEl.textContent = text;

  line.appendChild(roleEl);
  line.appendChild(textEl);
  els.chatWindow.appendChild(line);
  els.chatWindow.scrollTop = els.chatWindow.scrollHeight;
}

function renderRuntimePlaceholder(message) {
  els.runtimeLogWindow.textContent = message;
}

function renderAuthStatus() {
  if (state.authToken) {
    els.authStatus.textContent = 'Bearer token saved for this browser session.';
  } else {
    els.authStatus.textContent = 'No bearer token configured.';
  }
}

function storeToken(token) {
  const normalized = token.trim();
  state.authToken = normalized;
  els.accessToken.value = normalized;
  if (normalized) {
    window.sessionStorage.setItem(AUTH_TOKEN_KEY, normalized);
    window.localStorage.removeItem(AUTH_TOKEN_KEY);
  } else {
    window.sessionStorage.removeItem(AUTH_TOKEN_KEY);
    window.localStorage.removeItem(AUTH_TOKEN_KEY);
  }
  renderAuthStatus();
}

function renderRuntimeLogs(data) {
  const stdoutBlock = data.stdout_exists
    ? (data.stdout_tail || '[stdout file exists but no content yet]')
    : '[stdout not created yet]';
  const stderrBlock = data.stderr_exists
    ? (data.stderr_tail || '[stderr file exists but no content yet]')
    : '[stderr not created yet]';

  const content =
`--- stdout (${data.stdout_path}) ---
${stdoutBlock}

--- stderr (${data.stderr_path}) ---
${stderrBlock}`;

  if (content !== state.runtimeSnapshot) {
    const isNearBottom =
      els.runtimeLogWindow.scrollTop + els.runtimeLogWindow.clientHeight >=
      els.runtimeLogWindow.scrollHeight - 24;
    els.runtimeLogWindow.textContent = content;
    if (isNearBottom) {
      els.runtimeLogWindow.scrollTop = els.runtimeLogWindow.scrollHeight;
    }
    state.runtimeSnapshot = content;
  }
}

function clearSession() {
  state.sessionId = null;
  state.schedulerState = 'idle';
  els.sessionId.textContent = '-';
  els.jobId.textContent = '-';
  els.schedulerState.textContent = 'idle';
  els.remaining.textContent = '-';
  els.releaseBtn.disabled = true;
  state.runtimeSnapshot = '';
  state.runtimeLogError = '';
  renderRuntimePlaceholder('No active session. Allocate a vLLM session to stream runtime logs.');
  updateSendEnabled();
  stopPolling();
  stopRuntimePolling();
}

function formatRemaining(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

function updateSendEnabled() {
  const canSend = state.appId === 'vllm' && !!state.sessionId && state.schedulerState === 'RUNNING';
  els.sendBtn.disabled = !canSend;
  els.chatInput.disabled = !canSend;
}

async function api(path, options = {}) {
  if (!state.authToken) {
    throw new Error('Bearer token required. Save a token before using HPC-Link APIs.');
  }

  const headers = { ...(options.headers || {}) };
  if (!headers['Content-Type'] && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }
  headers.Authorization = `Bearer ${state.authToken}`;

  const response = await fetch(path, {
    headers,
    ...options,
  });

  const text = await response.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }

  if (!response.ok) {
    const detail = data.detail || `HTTP ${response.status}`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }

  return data;
}

function setOptions(selectEl, items, mapLabel, mapValue) {
  selectEl.innerHTML = '';
  for (const item of items) {
    const opt = document.createElement('option');
    opt.value = mapValue(item);
    opt.textContent = mapLabel(item);
    selectEl.appendChild(opt);
  }
}

async function loadApps() {
  const apps = await api('/api/apps');
  if (!Array.isArray(apps) || apps.length === 0) {
    throw new Error('No pre-specified applications returned by HPC-Link');
  }

  setOptions(
    els.appSelect,
    apps,
    (app) => `${app.name} (${app.app_id})`,
    (app) => app.app_id
  );

  state.appId = els.appSelect.value;
  log('event', `Loaded application catalog from HPC-Link: ${apps.map((a) => a.app_id).join(', ')}`);
}

async function loadModels() {
  if (state.appId !== 'vllm') {
    els.modelSelect.innerHTML = '';
    els.modelSelect.disabled = true;
    renderRuntimePlaceholder('Runtime log streaming is currently implemented for the vllm application.');
    return;
  }

  const models = await api('/api/vllm/models');
  if (!Array.isArray(models) || models.length === 0) {
    throw new Error('No vLLM models available via HPC-Link');
  }

  setOptions(
    els.modelSelect,
    models,
    (model) => `${model.label}${model.installed === false ? ' (missing)' : ''}`,
    (model) => model.model_id
  );

  els.modelSelect.disabled = false;
  log('event', `Loaded ${models.length} vLLM models from HPC-Link`);
}

async function refreshStatus() {
  if (!state.sessionId) {
    return;
  }

  const status = await api(`/api/vllm/sessions/${state.sessionId}`);
  const previous = state.schedulerState;
  state.schedulerState = status.scheduler_state || 'UNKNOWN';

  els.schedulerState.textContent = state.schedulerState;
  els.remaining.textContent = typeof status.remaining_seconds === 'number'
    ? formatRemaining(status.remaining_seconds)
    : '-';
  els.jobId.textContent = status.job_id || '-';

  if (previous !== state.schedulerState) {
    const reason = status.scheduler_reason ? `, reason=${status.scheduler_reason}` : '';
    log('event', `Scheduler state changed: ${state.schedulerState}${reason}`);
  }

  if (['COMPLETED', 'FAILED', 'CANCELLED', 'TIMEOUT', 'OUT_OF_MEMORY', 'NODE_FAIL'].includes(state.schedulerState)) {
    log('info', `Session reached terminal scheduler state: ${state.schedulerState}`);
  }

  updateSendEnabled();
}

async function refreshRuntimeLogs() {
  if (!state.sessionId || state.appId !== 'vllm') {
    return;
  }

  try {
    const runtime = await api(`/api/vllm/sessions/${state.sessionId}/logs?tail_lines=200`);
    renderRuntimeLogs(runtime);
    state.runtimeLogError = '';
  } catch (error) {
    if (error.message !== state.runtimeLogError) {
      log('error', `Runtime log stream failed: ${error.message}`);
      state.runtimeLogError = error.message;
    }
  }
}

function startPolling() {
  stopPolling();
  state.pollTimer = setInterval(async () => {
    try {
      await refreshStatus();
    } catch (error) {
      log('error', `Status polling failed: ${error.message}`);
    }
  }, 5000);
}

function stopPolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

function startRuntimePolling() {
  stopRuntimePolling();
  state.runtimePollTimer = setInterval(async () => {
    await refreshRuntimeLogs();
  }, 4000);
}

function stopRuntimePolling() {
  if (state.runtimePollTimer) {
    clearInterval(state.runtimePollTimer);
    state.runtimePollTimer = null;
  }
}

async function onAllocate() {
  if (state.appId !== 'vllm') {
    log('error', `Selected app '${state.appId}' is not wired in this demo. Use vllm.`);
    return;
  }

  const modelId = els.modelSelect.value;
  if (!modelId) {
    log('error', 'Cannot allocate: no model selected.');
    return;
  }

  const payload = {
    model_id: modelId,
    partition: els.partition.value || 'partition-a',
    duration_minutes: Number(els.duration.value) || 30,
    gpu_count: Number(els.gpuCount.value) || 1,
  };

  const gpuType = els.gpuType.value.trim();
  if (gpuType) {
    payload.gpu_type = gpuType;
  }

  log(
    'info',
    `Sending allocation request for app=vllm (model=${payload.model_id}, partition=${payload.partition}, duration=${payload.duration_minutes}m, gpus=${payload.gpu_count}).`
  );

  els.allocateBtn.disabled = true;
  try {
    const session = await api('/api/vllm/sessions', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    state.sessionId = session.session_id;
    state.schedulerState = session.status || 'queued';
    els.sessionId.textContent = session.session_id || '-';
    els.jobId.textContent = session.job_id || '-';
    els.schedulerState.textContent = state.schedulerState;
    els.remaining.textContent = '-';
    els.releaseBtn.disabled = false;
    state.runtimeSnapshot = '';
    state.runtimeLogError = '';
    renderRuntimePlaceholder('Waiting for SLURM/vLLM logs...');

    addChat('system', `Allocated session ${session.session_id} (job ${session.job_id}).`);
    log('success', `Allocation created: session=${session.session_id}, job=${session.job_id}`);

    await refreshStatus();
    await refreshRuntimeLogs();
    startPolling();
    startRuntimePolling();
  } catch (error) {
    log('error', `Allocation failed: ${error.message}`);
  } finally {
    els.allocateBtn.disabled = false;
    updateSendEnabled();
  }
}

async function onRelease() {
  if (!state.sessionId) {
    return;
  }

  const active = state.sessionId;
  log('info', `Sending release request for session=${active}`);

  try {
    const result = await api(`/api/vllm/sessions/${active}`, { method: 'DELETE' });
    addChat('system', result.message || `Released session ${active}`);
    log('success', result.message || `Session ${active} released`);
  } catch (error) {
    log('error', `Release failed: ${error.message}`);
  } finally {
    clearSession();
  }
}

async function onSendChat(event) {
  event.preventDefault();

  const message = els.chatInput.value.trim();
  if (!message || !state.sessionId || state.schedulerState !== 'RUNNING') {
    return;
  }

  const payload = {
    message,
    temperature: Number(els.temperature.value) || 0.2,
    max_tokens: Number(els.maxTokens.value) || 256,
  };

  addChat('user', message);
  els.chatInput.value = '';
  els.sendBtn.disabled = true;
  log('info', `Sending chat request (${message.length} chars).`);

  try {
    const response = await api(`/api/vllm/sessions/${state.sessionId}/chat`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    addChat('assistant', response.reply || '[empty reply]');
    log(
      'success',
      `Chat response received (prompt_tokens=${response.usage_prompt_tokens ?? '-'}, completion_tokens=${response.usage_completion_tokens ?? '-'})`
    );
  } catch (error) {
    addChat('system', `Chat failed: ${error.message}`);
    log('error', `Chat failed: ${error.message}`);
  } finally {
    updateSendEnabled();
  }
}

async function onApplicationChanged() {
  state.appId = els.appSelect.value;
  log('event', `Selected application changed to '${state.appId}'.`);

  if (state.sessionId) {
    log('info', 'Releasing active session because application changed.');
    await onRelease();
  }

  try {
    await loadModels();
  } catch (error) {
    log('error', `Could not load models: ${error.message}`);
  }

  updateSendEnabled();
}

async function initialize() {
  storeToken(window.sessionStorage.getItem(AUTH_TOKEN_KEY) || window.localStorage.getItem(AUTH_TOKEN_KEY) || '');
  log('info', 'HPC-Linktest started. Verifying upstream and loading pre-specified app catalog.');

  if (!state.authToken) {
    log('error', 'No bearer token configured. Add a token to continue.');
    updateSendEnabled();
    return;
  }

  try {
    const health = await api('/api/hpc-link/health');
    log('success', `HPC-Link health check: ${health.status || 'ok'}`);
  } catch (error) {
    log('error', `HPC-Link health check failed: ${error.message}`);
  }

  try {
    await loadApps();
    await loadModels();
  } catch (error) {
    log('error', `Initialization failed: ${error.message}`);
  }

  updateSendEnabled();
}

els.allocateBtn.addEventListener('click', onAllocate);
els.releaseBtn.addEventListener('click', onRelease);
els.chatForm.addEventListener('submit', onSendChat);
els.appSelect.addEventListener('change', onApplicationChanged);
els.saveTokenBtn.addEventListener('click', async () => {
  storeToken(els.accessToken.value);
  if (state.authToken) {
    log('success', 'Bearer token saved.');
    clearSession();
    await initialize();
  } else {
    log('error', 'Token is empty.');
  }
});
els.clearTokenBtn.addEventListener('click', () => {
  storeToken('');
  clearSession();
  log('info', 'Bearer token removed.');
});
els.clearLog.addEventListener('click', () => {
  els.logWindow.innerHTML = '';
  log('info', 'Log cleared.');
});
els.clearRuntimeLog.addEventListener('click', () => {
  state.runtimeSnapshot = '';
  renderRuntimePlaceholder('Runtime log view cleared. Waiting for next stream update...');
});

window.addEventListener('beforeunload', () => {
  stopPolling();
  stopRuntimePolling();
});

renderRuntimePlaceholder('No active session. Allocate a vLLM session to stream runtime logs.');
renderAuthStatus();
initialize();
