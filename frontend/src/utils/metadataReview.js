export function metadataText(value) {
  if (Array.isArray(value)) return value.map(metadataText).filter(Boolean).join(', ')
  if (value && typeof value === 'object') return metadataText(value.name || value.title || value.identifier || value.id)
  return value == null ? '' : String(value).trim()
}

export function metadataQuality(entries) {
  const missing = { title: 0, description: 0, creators: 0 }
  let needsReview = 0
  for (const [, metadata] of entries) {
    let incomplete = false
    for (const field of Object.keys(missing)) {
      const value = field === 'creators' ? metadata.creators || metadata.creator : metadata[field]
      if (!metadataText(value)) { missing[field]++; incomplete = true }
    }
    if (incomplete) needsReview++
  }
  return { total: entries.length, needsReview, missing }
}
