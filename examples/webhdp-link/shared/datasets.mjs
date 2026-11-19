function assetUrl(value) {
  const url = new URL(value, location.origin)
  if (url.origin !== location.origin || url.search || url.hash ||
      !/^\/(datasets|fixtures)\//.test(url.pathname)) {
    throw new Error('A test dataset asset points outside the application.')
  }
  return url.href
}

function element(tag, text, className) {
  const node = document.createElement(tag)
  if (text) node.textContent = text
  if (className) node.className = className
  return node
}

export function renderDatasetCard(dataset, select) {
  const card = element('article', '', 'dataset')
  const image = element('img', '', 'dataset-preview')
  image.src = assetUrl(dataset.preview.url)
  image.alt = dataset.preview.alt
  image.decoding = 'async'

  const body = element('div', '', 'dataset-body')
  const title = element('h3', dataset.title)
  const summary = element('p', dataset.summary, 'dataset-summary')
  const facts = element('dl', '', 'dataset-facts')
  for (const fact of dataset.facts) {
    const row = element('div')
    row.append(element('dt', fact.label), element('dd', fact.value))
    facts.append(row)
  }

  const credit = element('p', '', 'dataset-credit')
  if (dataset.credit.url && new URL(dataset.credit.url).protocol === 'https:') {
    const link = element('a', dataset.credit.label)
    link.href = dataset.credit.url
    link.target = '_blank'
    link.rel = 'noopener noreferrer'
    credit.append(link)
  } else {
    credit.textContent = dataset.credit.label
  }

  const button = element('button', 'Load dataset', 'secondary dataset-load')
  button.type = 'button'
  button.setAttribute('aria-label', `Load ${dataset.title}`)
  button.setAttribute('aria-pressed', 'false')
  button.addEventListener('click', () => select(dataset))
  body.append(title, summary, facts, credit, button)
  card.append(image, body)
  return { card, button }
}

export async function loadDatasetFiles(entries, signal) {
  return Promise.all(entries.map(async entry => {
    const response = await fetch(assetUrl(entry.url), { signal, redirect: 'error' })
    if (!response.ok) throw new Error(`Could not load ${entry.name}.`)
    const blob = await response.blob()
    if (entry.sha256) {
      const bytes = await blob.arrayBuffer()
      const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))
      const sha256 = Array.from(digest, value => value.toString(16).padStart(2, '0')).join('')
      if (blob.size !== entry.bytes || sha256 !== entry.sha256) {
        throw new Error(`The test file ${entry.name} could not be verified.`)
      }
    }
    return new File([blob], entry.name, { type: blob.type })
  }))
}
