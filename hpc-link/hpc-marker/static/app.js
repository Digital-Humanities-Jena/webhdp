const AUTH_TOKEN_KEY = 'hpc_link_access_token';

const state = {
  authToken: '',
  sessionId: null,
  jobId: null,
  schedulerState: 'idle',
  pollTimer: null,
  runtimePollTimer: null,
  runtimeSnapshot: '',
};

const els = {
  accessToken: document.getElementById('access-token'),
  saveTokenBtn: document.getElementById('save-token-btn'),
  clearTokenBtn: document.getElementById('clear-token-btn'),
  authStatus: document.getElementById('auth-status'),
  partition: document.getElementById('partition'),
  gpuCount: document.getElementById('gpu-count'),
  duration: document.getElementById('duration'),
  torchDevice: document.getElementById('torch-device'),
  allocateBtn: document.getElementById('allocate-btn'),
  releaseBtn: document.getElementById('release-btn'),
  sessionId: document.getElementById('session-id'),
  jobId: document.getElementById('job-id'),
  schedulerState: document.getElementById('scheduler-state'),
  remaining: document.getElementById('remaining'),
  documentFile: document.getElementById('document-file'),
  uploadBtn: document.getElementById('upload-btn'),
  inputFilename: document.getElementById('input-filename'),
  outputFormat: document.getElementById('output-format'),
  pageRange: document.getElementById('page-range'),
  forceOcr: document.getElementById('force-ocr'),
  useLlm: document.getElementById('use-llm'),
  convertBtn: document.getElementById('convert-btn'),
  refreshArtifactsBtn: document.getElementById('refresh-artifacts-btn'),
  artifactList: document.getElementById('artifact-list'),
  logWindow: document.getElementById('log-window'),
  runtimeLogWindow: document.getElementById('runtime-log-window'),
  clearLog: document.getElementById('clear-log'),
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
  els.authStatus.textContent = normalized
    ? 'Bearer token saved for this browser session.'
    : 'No bearer token configured.';
}

function formatRemaining(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

function clearSessionState() {
  state.sessionId = null;
  state.jobId = null;
  state.schedulerState = 'idle';
  els.sessionId.textContent = '-';
  els.jobId.textContent = '-';
  els.schedulerState.textContent = 'idle';
  els.remaining.textContent = '-';
  els.inputFilename.value = '';
  els.artifactList.textContent = 'No artifacts yet.';
  els.runtimeLogWindow.textContent = 'No active session.';
  stopPolling();
  stopRuntimePolling();
  setActionState();
}

function setActionState() {
  const hasSession = !!state.sessionId;
  const isRunning = state.schedulerState === 'RUNNING';
  const hasFile = !!els.documentFile.files[0];
  const hasInputName = !!els.inputFilename.value.trim();
  els.releaseBtn.disabled = !hasSession;
  els.uploadBtn.disabled = !hasSession || !hasFile;
  els.convertBtn.disabled = !hasSession || !isRunning || !hasInputName;
  els.refreshArtifactsBtn.disabled = !hasSession;
}

async function api(path, options = {}) {
  if (!state.authToken) {
    throw new Error('Bearer token required. Save token first.');
  }

  const headers = { ...(options.headers || {}) };
  if (!headers['Content-Type'] && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }
  headers.Authorization = `Bearer ${state.authToken}`;

  const response = await fetch(path, { ...options, headers });
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
  const hasMarker = Array.isArray(apps) && apps.some((app) => app.app_id === 'marker');
  if (!hasMarker) {
    throw new Error('HPC-Link /api/apps does not expose app_id=marker.');
  }
  log('event', `Application catalog confirms marker adapter (${apps.length} app entries).`);
}

async function refreshStatus() {
  if (!state.sessionId) return;
  const status = await api(`/api/marker/sessions/${state.sessionId}`);
  state.schedulerState = status.scheduler_state || 'UNKNOWN';
  state.jobId = status.job_id || state.jobId;
  els.schedulerState.textContent = state.schedulerState;
  els.jobId.textContent = state.jobId || '-';
  els.remaining.textContent = typeof status.remaining_seconds === 'number'
    ? formatRemaining(status.remaining_seconds)
    : '-';
  setActionState();
}

async function refreshRuntimeLogs() {
  if (!state.sessionId) return;
  try {
    const runtime = await api(`/api/marker/sessions/${state.sessionId}/logs?tail_lines=200`);
    const stdout = runtime.stdout_exists ? (runtime.stdout_tail || '[stdout empty]') : '[stdout not created yet]';
    const stderr = runtime.stderr_exists ? (runtime.stderr_tail || '[stderr empty]') : '[stderr not created yet]';
    const next = `--- stdout (${runtime.stdout_path}) ---\n${stdout}\n\n--- stderr (${runtime.stderr_path}) ---\n${stderr}`;
    if (next !== state.runtimeSnapshot) {
      els.runtimeLogWindow.textContent = next;
      state.runtimeSnapshot = next;
    }
  } catch (error) {
    log('error', `Runtime log stream failed: ${error.message}`);
  }
}

function startPolling() {
  stopPolling();
  state.pollTimer = setInterval(async () => {
    try {
      await refreshStatus();
    } catch (error) {
      log('error', `Status poll failed: ${error.message}`);
      stopPolling();
    }
  }, 3500);
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
  }, 3500);
}

function stopRuntimePolling() {
  if (state.runtimePollTimer) {
    clearInterval(state.runtimePollTimer);
    state.runtimePollTimer = null;
  }
}

function renderArtifacts(artifacts) {
  if (!Array.isArray(artifacts) || artifacts.length === 0) {
    els.artifactList.textContent = 'No artifacts yet.';
    return;
  }
  els.artifactList.innerHTML = '';
  artifacts.forEach((artifact) => {
    const row = document.createElement('div');
    row.className = 'artifact-row';

    const meta = document.createElement('div');
    meta.textContent = `${artifact.name} (${Math.max(1, Math.round(artifact.size_bytes / 1024))} KB)`;

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'download-link';
    button.textContent = 'Download';
    button.addEventListener('click', async () => {
      try {
        const response = await fetch(
          `/api/marker/sessions/${encodeURIComponent(state.sessionId)}/artifacts/${encodeURIComponent(artifact.name)}/download`,
          {
            headers: { Authorization: `Bearer ${state.authToken}` },
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
        link.download = artifact.name;
        link.click();
        URL.revokeObjectURL(objectUrl);
        log('success', `Downloaded ${artifact.name}`);
      } catch (error) {
        log('error', `Download failed for ${artifact.name}: ${error.message}`);
      }
    });

    row.appendChild(meta);
    row.appendChild(button);
    els.artifactList.appendChild(row);
  });
}

els.saveTokenBtn.addEventListener('click', () => {
  storeToken(els.accessToken.value);
  log('event', 'Saved bearer token');
});

els.clearTokenBtn.addEventListener('click', () => {
  storeToken('');
  log('event', 'Cleared bearer token');
});

els.allocateBtn.addEventListener('click', async () => {
  try {
    await verifyApps();
    const payload = {
      partition: els.partition.value.trim(),
      gpu_count: Number(els.gpuCount.value),
      duration_minutes: Number(els.duration.value),
      torch_device: els.torchDevice.value,
    };
    const created = await api('/api/marker/sessions', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    state.sessionId = created.session_id;
    state.jobId = created.job_id;
    state.schedulerState = 'PENDING';
    els.sessionId.textContent = state.sessionId;
    els.jobId.textContent = state.jobId;
    els.schedulerState.textContent = state.schedulerState;
    els.remaining.textContent = '-';
    state.runtimeSnapshot = '';
    log('success', `Allocated marker session ${state.sessionId} (job ${state.jobId})`);
    setActionState();
    await refreshStatus();
    await refreshRuntimeLogs();
    startPolling();
    startRuntimePolling();
  } catch (error) {
    log('error', `Allocation failed: ${error.message}`);
  }
});

els.releaseBtn.addEventListener('click', async () => {
  if (!state.sessionId) return;
  try {
    await api(`/api/marker/sessions/${state.sessionId}`, { method: 'DELETE' });
    log('success', `Released marker session ${state.sessionId}`);
  } catch (error) {
    log('error', `Release failed: ${error.message}`);
  } finally {
    clearSessionState();
  }
});

els.documentFile.addEventListener('change', () => {
  const file = els.documentFile.files[0];
  if (file && !els.inputFilename.value.trim()) {
    els.inputFilename.value = file.name;
  }
  setActionState();
});

els.inputFilename.addEventListener('input', setActionState);

els.uploadBtn.addEventListener('click', async () => {
  if (!state.sessionId) return;
  const file = els.documentFile.files[0];
  if (!file) {
    log('error', 'Choose one document first.');
    return;
  }

  const form = new FormData();
  form.append('file', file);
  try {
    const uploaded = await api(`/api/marker/sessions/${state.sessionId}/documents`, {
      method: 'POST',
      body: form,
    });
    els.inputFilename.value = uploaded.filename;
    log('success', `Uploaded ${uploaded.filename} (${uploaded.size_bytes} bytes)`);
    setActionState();
  } catch (error) {
    log('error', `Upload failed: ${error.message}`);
  }
});

els.convertBtn.addEventListener('click', async () => {
  if (!state.sessionId) return;
  const payload = {
    input_filename: els.inputFilename.value.trim(),
    output_format: els.outputFormat.value,
    force_ocr: els.forceOcr.checked,
    use_llm: els.useLlm.checked,
  };
  const pageRange = els.pageRange.value.trim();
  if (pageRange) {
    payload.page_range = pageRange;
  }

  try {
    const result = await api(`/api/marker/sessions/${state.sessionId}/convert`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    renderArtifacts(result.artifacts || []);
    log('success', `Conversion finished. ${result.artifact_count} artifact(s) available.`);
  } catch (error) {
    log('error', `Conversion failed: ${error.message}`);
  }
});

els.refreshArtifactsBtn.addEventListener('click', async () => {
  if (!state.sessionId) return;
  try {
    const result = await api(`/api/marker/sessions/${state.sessionId}/artifacts`);
    renderArtifacts(result.artifacts || []);
    log('event', `Artifact list refreshed (${(result.artifacts || []).length} files).`);
  } catch (error) {
    log('error', `Artifact refresh failed: ${error.message}`);
  }
});

els.clearLog.addEventListener('click', () => {
  els.logWindow.textContent = '';
});

els.clearRuntimeLog.addEventListener('click', () => {
  state.runtimeSnapshot = '';
  els.runtimeLogWindow.textContent = '';
});

window.addEventListener('beforeunload', () => {
  stopPolling();
  stopRuntimePolling();
});

(() => {
  const token = window.sessionStorage.getItem(AUTH_TOKEN_KEY) || '';
  storeToken(token);
  clearSessionState();
})();
