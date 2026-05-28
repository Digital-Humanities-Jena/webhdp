const state = {
  sessionId: null,
  jobId: null,
  schedulerState: 'idle',
  pollTimer: null,
  runtimePollTimer: null,
  runtimeSnapshot: '',
  runtimeLogError: '',
  uploadedFiles: [],
  artifacts: [],
  authToken: '',
};

const AUTH_TOKEN_KEY = 'hpc_link_access_token';

const els = {
  accessToken: document.getElementById('access-token'),
  saveTokenBtn: document.getElementById('save-token-btn'),
  clearTokenBtn: document.getElementById('clear-token-btn'),
  authStatus: document.getElementById('auth-status'),
  partition: document.getElementById('partition'),
  gpuCount: document.getElementById('gpu-count'),
  duration: document.getElementById('duration'),
  cudaModule: document.getElementById('cuda-module'),
  allocateBtn: document.getElementById('allocate-btn'),
  releaseBtn: document.getElementById('release-btn'),
  sessionId: document.getElementById('session-id'),
  jobId: document.getElementById('job-id'),
  schedulerState: document.getElementById('scheduler-state'),
  remaining: document.getElementById('remaining'),
  imageFiles: document.getElementById('image-files'),
  uploadBtn: document.getElementById('upload-btn'),
  uploadedList: document.getElementById('uploaded-list'),
  outputName: document.getElementById('output-name'),
  interval: document.getElementById('interval'),
  processBtn: document.getElementById('process-btn'),
  refreshArtifactsBtn: document.getElementById('refresh-artifacts-btn'),
  artifactList: document.getElementById('artifact-list'),
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

function setActionsEnabled() {
  const hasSession = !!state.sessionId;
  const isRunning = state.schedulerState === 'RUNNING';
  els.releaseBtn.disabled = !hasSession;
  els.uploadBtn.disabled = !hasSession;
  els.processBtn.disabled = !hasSession || !isRunning || state.uploadedFiles.length === 0;
  els.refreshArtifactsBtn.disabled = !hasSession;
}

function renderUploadedList() {
  if (state.uploadedFiles.length === 0) {
    els.uploadedList.textContent = 'No uploaded files yet.';
    return;
  }
  els.uploadedList.innerHTML = '';
  state.uploadedFiles.forEach((name) => {
    const row = document.createElement('div');
    row.className = 'list-row';
    row.textContent = name;
    els.uploadedList.appendChild(row);
  });
}

function renderArtifactList() {
  if (state.artifacts.length === 0) {
    els.artifactList.textContent = 'No artifacts yet.';
    return;
  }

  els.artifactList.innerHTML = '';
  state.artifacts.forEach((artifact) => {
    const row = document.createElement('div');
    row.className = 'list-row row-between';

    const meta = document.createElement('div');
    meta.textContent = `${artifact.name} (${Math.max(1, Math.round(artifact.size_bytes / 1024))} KB)`;

    const action = document.createElement('button');
    action.type = 'button';
    action.textContent = 'Download';
    action.className = 'download-link';
    action.addEventListener('click', async () => {
      try {
        await downloadArtifact(artifact.name);
      } catch (error) {
        log('error', `Download failed for ${artifact.name}: ${error.message}`);
      }
    });

    row.appendChild(meta);
    row.appendChild(action);
    els.artifactList.appendChild(row);
  });
}

async function downloadArtifact(artifactName) {
  if (!state.authToken) {
    throw new Error('Bearer token required.');
  }
  if (!state.sessionId) {
    throw new Error('No active session.');
  }

  const response = await fetch(
    `/api/pi3/sessions/${encodeURIComponent(state.sessionId)}/artifacts/${encodeURIComponent(artifactName)}/download`,
    {
      headers: {
        Authorization: `Bearer ${state.authToken}`,
      },
    },
  );

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = objectUrl;
  link.download = artifactName;
  link.click();
  URL.revokeObjectURL(objectUrl);
  log('success', `Downloaded artifact: ${artifactName}`);
}

function clearSessionState() {
  state.sessionId = null;
  state.jobId = null;
  state.schedulerState = 'idle';
  state.uploadedFiles = [];
  state.artifacts = [];
  state.runtimeSnapshot = '';
  state.runtimeLogError = '';

  els.sessionId.textContent = '-';
  els.jobId.textContent = '-';
  els.schedulerState.textContent = 'idle';
  els.remaining.textContent = '-';
  renderUploadedList();
  renderArtifactList();
  renderRuntimePlaceholder('No active session. Allocate a Pi3 session to stream runtime logs.');

  stopPolling();
  stopRuntimePolling();
  setActionsEnabled();
}

function formatRemaining(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
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
    ...options,
    headers,
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

async function verifyApps() {
  const apps = await api('/api/apps');
  const hasPi3 = Array.isArray(apps) && apps.some((app) => app.app_id === 'pi3');
  if (!hasPi3) {
    throw new Error('HPC-Link /api/apps does not expose app_id=pi3.');
  }
  log('event', `Application catalog confirms pi3 adapter (${apps.length} app entries).`);
}

async function refreshStatus() {
  if (!state.sessionId) {
    return;
  }

  const status = await api(`/api/pi3/sessions/${state.sessionId}`);
  const previous = state.schedulerState;
  state.schedulerState = status.scheduler_state || 'UNKNOWN';
  state.jobId = status.job_id || state.jobId;

  els.schedulerState.textContent = state.schedulerState;
  els.jobId.textContent = state.jobId || '-';
  els.remaining.textContent = typeof status.remaining_seconds === 'number'
    ? formatRemaining(status.remaining_seconds)
    : '-';

  if (previous !== state.schedulerState) {
    const reason = status.scheduler_reason ? `, reason=${status.scheduler_reason}` : '';
    log('event', `Scheduler state changed: ${state.schedulerState}${reason}`);
  }

  setActionsEnabled();
}

async function refreshRuntimeLogs() {
  if (!state.sessionId) {
    return;
  }

  try {
    const runtime = await api(`/api/pi3/sessions/${state.sessionId}/logs?tail_lines=200`);
    renderRuntimeLogs(runtime);
    state.runtimeLogError = '';
  } catch (error) {
    if (error.message !== state.runtimeLogError) {
      log('error', `Runtime log stream failed: ${error.message}`);
      state.runtimeLogError = error.message;
    }
  }
}

async function refreshArtifacts() {
  if (!state.sessionId) {
    return;
  }

  const data = await api(`/api/pi3/sessions/${state.sessionId}/artifacts`);
  state.artifacts = Array.isArray(data.artifacts) ? data.artifacts : [];
  renderArtifactList();
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
  const payload = {
    partition: els.partition.value,
    gpu_count: Number(els.gpuCount.value) || 1,
    duration_minutes: Number(els.duration.value) || 30,
  };

  const cudaModule = els.cudaModule.value.trim();
  if (cudaModule) {
    payload.cuda_module = cudaModule;
  }

  els.allocateBtn.disabled = true;
  log('info', `Allocating Pi3 session (partition=${payload.partition}, gpus=${payload.gpu_count}, duration=${payload.duration_minutes}m).`);

  try {
    const session = await api('/api/pi3/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    state.sessionId = session.session_id;
    state.jobId = session.job_id;
    state.schedulerState = 'queued';
    state.uploadedFiles = [];
    state.artifacts = [];
    state.runtimeSnapshot = '';

    els.sessionId.textContent = session.session_id || '-';
    els.jobId.textContent = session.job_id || '-';
    els.schedulerState.textContent = state.schedulerState;
    els.remaining.textContent = '-';

    renderUploadedList();
    renderArtifactList();
    renderRuntimePlaceholder('Waiting for SLURM/Pi3 logs...');

    log('success', `Session allocated: session=${session.session_id}, job=${session.job_id}`);

    await refreshStatus();
    await refreshRuntimeLogs();
    await refreshArtifacts();
    startPolling();
    startRuntimePolling();
  } catch (error) {
    log('error', `Allocation failed: ${error.message}`);
  } finally {
    els.allocateBtn.disabled = false;
    setActionsEnabled();
  }
}

async function onRelease() {
  if (!state.sessionId) {
    return;
  }

  const active = state.sessionId;
  log('info', `Sending release request for session=${active}`);
  try {
    const result = await api(`/api/pi3/sessions/${active}`, { method: 'DELETE' });
    log('success', result.message || `Session ${active} released`);
  } catch (error) {
    log('error', `Release failed: ${error.message}`);
  } finally {
    clearSessionState();
  }
}

async function onUpload() {
  if (!state.sessionId) {
    log('error', 'No active session. Allocate first.');
    return;
  }

  const files = Array.from(els.imageFiles.files || []);
  if (files.length === 0) {
    log('error', 'Select at least one image file.');
    return;
  }

  els.uploadBtn.disabled = true;
  let uploadedCount = 0;

  try {
    for (const file of files) {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(`/api/pi3/sessions/${encodeURIComponent(state.sessionId)}/images`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${state.authToken}`,
        },
        body: formData,
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

      if (!state.uploadedFiles.includes(file.name)) {
        state.uploadedFiles.push(file.name);
      }
      uploadedCount += 1;
      log('event', `Uploaded ${file.name}`);
    }

    renderUploadedList();
    log('success', `Uploaded ${uploadedCount} image(s) to the active Pi3 session.`);
  } catch (error) {
    log('error', `Upload failed: ${error.message}`);
  } finally {
    els.uploadBtn.disabled = false;
    setActionsEnabled();
  }
}

async function onProcess() {
  if (!state.sessionId) {
    return;
  }

  const payload = {
    output_name: (els.outputName.value || 'result.ply').trim(),
    interval: Number(els.interval.value) || 1,
  };

  els.processBtn.disabled = true;
  log('info', `Starting Pi3 processing (output=${payload.output_name}, interval=${payload.interval}).`);

  try {
    const result = await api(`/api/pi3/sessions/${state.sessionId}/process`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    log('success', `Pi3 finished: ${result.output_name} (${result.size_bytes} bytes).`);
    await refreshArtifacts();
  } catch (error) {
    log('error', `Pi3 processing failed: ${error.message}`);
  } finally {
    setActionsEnabled();
  }
}

async function initialize() {
  storeToken(window.sessionStorage.getItem(AUTH_TOKEN_KEY) || window.localStorage.getItem(AUTH_TOKEN_KEY) || '');
  log('info', 'HPC-Pi3 started. Verifying upstream and app catalog.');

  if (!state.authToken) {
    log('error', 'No bearer token configured. Add a token to continue.');
    setActionsEnabled();
    return;
  }

  try {
    const health = await api('/api/hpc-link/health');
    log('success', `HPC-Link health check: ${health.status || 'ok'}`);
  } catch (error) {
    log('error', `HPC-Link health check failed: ${error.message}`);
  }

  try {
    await verifyApps();
  } catch (error) {
    log('error', `Initialization failed: ${error.message}`);
  }

  setActionsEnabled();
}

els.allocateBtn.addEventListener('click', onAllocate);
els.releaseBtn.addEventListener('click', onRelease);
els.uploadBtn.addEventListener('click', onUpload);
els.processBtn.addEventListener('click', onProcess);
els.saveTokenBtn.addEventListener('click', async () => {
  storeToken(els.accessToken.value);
  if (state.authToken) {
    log('success', 'Bearer token saved.');
    clearSessionState();
    await initialize();
  } else {
    log('error', 'Token is empty.');
  }
});
els.clearTokenBtn.addEventListener('click', () => {
  storeToken('');
  clearSessionState();
  log('info', 'Bearer token removed.');
});
els.refreshArtifactsBtn.addEventListener('click', async () => {
  try {
    await refreshArtifacts();
    log('event', 'Artifacts refreshed.');
  } catch (error) {
    log('error', `Could not refresh artifacts: ${error.message}`);
  }
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

renderRuntimePlaceholder('No active session. Allocate a Pi3 session to stream runtime logs.');
renderUploadedList();
renderArtifactList();
renderAuthStatus();
initialize();
