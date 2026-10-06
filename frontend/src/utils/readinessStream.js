export function readinessStream(onProgress = () => {}) {
  let consumed = 0
  let result = null
  let failure = null
  return {
    consume(text, final = false) {
      if (typeof text !== 'string') return text
      if (final && text.trimStart().startsWith('{') && !text.includes('"type"')) {
        const envelope = JSON.parse(text)
        if (envelope.data) return envelope
      }
      const end = final ? text.length : text.lastIndexOf('\n') + 1
      for (const line of text.slice(consumed, end).split('\n').filter(Boolean)) {
        const event = JSON.parse(line)
        if (event.type === 'progress') onProgress({ checked: event.checked, total: event.total })
        if (event.type === 'result') result = { data: event.report }
        if (event.type === 'error') failure = event.message
        if (!event.type && event.data) result = event
      }
      consumed = end
      if (final && (failure || !result)) throw new Error(failure || 'Readiness ended before its result was received. Check again.')
      return result
    },
  }
}
