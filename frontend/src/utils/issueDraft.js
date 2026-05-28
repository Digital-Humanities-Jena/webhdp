const ISSUE_DRAFT_STORAGE_KEY = 'webhdp_issue_report_context'

function normalizeScalar(value) {
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'string' && /^\d+$/.test(value)) return Number(value)
  return value
}

function toSnakeCase(value) {
  return String(value || '')
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .replace(/[^a-zA-Z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toLowerCase()
}

export function deriveRelatedEntityIds(route) {
  const params = route?.params && typeof route.params === 'object' ? route.params : {}
  const related = {}

  Object.entries(params).forEach(([key, rawValue]) => {
    const value = normalizeScalar(rawValue)
    if (value === null || value === undefined) {
      return
    }
    related[key] = value
    const snakeKey = toSnakeCase(key)
    if (snakeKey && related[snakeKey] === undefined) {
      related[snakeKey] = value
    }
  })

  if (route?.name === 'SubmissionDetail' && related.id !== undefined && related.submission_id === undefined) {
    related.submission_id = related.id
  }
  if (route?.name === 'AdminReview' && related.id !== undefined && related.submission_id === undefined) {
    related.submission_id = related.id
  }

  return related
}

export function buildIssueDraftContext({ route, user, appVersion = null } = {}) {
  const params = route?.params && typeof route.params === 'object' ? route.params : {}
  const query = route?.query && typeof route.query === 'object' ? route.query : {}
  const environmentContext = {
    app_version: appVersion || null,
    viewport: typeof window !== 'undefined'
      ? { width: window.innerWidth, height: window.innerHeight }
      : {},
    language: typeof navigator !== 'undefined' ? navigator.language : null,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || null,
    user_agent: typeof navigator !== 'undefined' ? navigator.userAgent : null,
  }

  const userContext = {
    reporter_id: user?.id || null,
    reporter_email: user?.email || null,
    reporter_role: user?.role || 'user',
    reporter_groups: Array.isArray(user?.groups) ? user.groups : [],
    reporter_capabilities: Array.isArray(user?.capabilities) ? user.capabilities : [],
  }

  return {
    route_name: route?.name || null,
    route_path: route?.path || null,
    current_url: typeof window !== 'undefined' ? window.location.href : null,
    route_context: {
      path: route?.path || null,
      full_path: route?.fullPath || null,
      params: { ...params },
      query: { ...query },
      matched: Array.isArray(route?.matched)
        ? route.matched.map((entry) => ({ path: entry.path, name: entry.name || null }))
        : [],
    },
    related_entity_ids: deriveRelatedEntityIds(route),
    environment_context: environmentContext,
    user_context: userContext,
    capture_context: {
      captured_at: new Date().toISOString(),
      source: 'main_layout_report_issue',
      route_snapshot: {
        name: route?.name || null,
        path: route?.path || null,
        full_path: route?.fullPath || null,
      },
    },
  }
}

export function saveIssueDraftContext(context) {
  if (typeof window === 'undefined') {
    return
  }
  try {
    window.sessionStorage.setItem(ISSUE_DRAFT_STORAGE_KEY, JSON.stringify(context || {}))
  } catch {
    // Ignore storage failures and allow the report page to build fresh context.
  }
}

export function loadIssueDraftContext() {
  if (typeof window === 'undefined') {
    return null
  }
  try {
    const raw = window.sessionStorage.getItem(ISSUE_DRAFT_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

export function consumeIssueDraftContext() {
  const context = loadIssueDraftContext()
  clearIssueDraftContext()
  return context
}

export function clearIssueDraftContext() {
  if (typeof window === 'undefined') {
    return
  }
  try {
    window.sessionStorage.removeItem(ISSUE_DRAFT_STORAGE_KEY)
  } catch {
    // Ignore storage failures.
  }
}
