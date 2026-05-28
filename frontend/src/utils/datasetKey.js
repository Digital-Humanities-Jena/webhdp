export const inferDatasetKey = (...values) => {
  for (const rawValue of values) {
    const text = String(rawValue || '').trim()
    if (!text) continue
    const segments = text.replaceAll('\\', '/').split('/').filter(Boolean)
    for (const segment of segments) {
      if (segment.toLowerCase().endsWith('_dataset')) {
        return segment
      }
    }
  }
  return ''
}

export const buildDatasetRoute = (datasetKey, query = null) => {
  const normalized = String(datasetKey || '').trim()
  const basePath = normalized ? `/datasets/${encodeURIComponent(normalized)}` : '/datasets'
  if (!query || typeof query !== 'object') {
    return basePath
  }
  const search = new URLSearchParams()
  Object.entries(query).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    search.set(key, String(value))
  })
  const queryString = search.toString()
  return queryString ? `${basePath}?${queryString}` : basePath
}
