import { ref, onMounted, onBeforeUnmount, toValue, watch } from 'vue'

export function useAutoSave(saveFunction, data, options = {}) {
  const { interval = 30000, debounce = null, immediate = false, enabled = true, draftKey = null } = options
  const isSaving = ref(false)
  const lastSaved = ref(null)
  const saveError = ref(null)
  const dirty = ref(false)
  const localDraftSaved = ref(false)
  const draftStorageError = ref(null)
  let timer
  let inFlight = null
  let revision = 0
  let queued = false
  let paused = false
  let disposed = false

  function retainDraft() {
    const key = toValue(draftKey)
    if (!key || !dirty.value) return false
    try {
      sessionStorage.setItem(key, JSON.stringify({ version: 1, data: toValue(data) }))
      localDraftSaved.value = true
      draftStorageError.value = null
      return true
    } catch (error) {
      localDraftSaved.value = false
      draftStorageError.value = error
      return false
    }
  }

  function markSaved() {
    dirty.value = false
    localDraftSaved.value = false
    const key = toValue(draftKey)
    if (key) {
      try { sessionStorage.removeItem(key) } catch (error) { draftStorageError.value = error }
    }
  }

  function restoreDraft() {
    dirty.value = false
    const key = toValue(draftKey)
    if (!key) return false
    try {
      const draft = JSON.parse(sessionStorage.getItem(key) || 'null')
      if (draft?.version !== 1 || !draft.data || typeof draft.data !== 'object' || Array.isArray(draft.data)) return false
      Object.assign(toValue(data), draft.data)
      dirty.value = true
      localDraftSaved.value = true
      return true
    } catch (error) {
      draftStorageError.value = error
      return false
    }
  }

  function beforeUnload(event) {
    const needsProtection = toValue(enabled) || localDraftSaved.value || draftStorageError.value
    if (dirty.value && needsProtection && toValue(draftKey) && !retainDraft()) {
      event.preventDefault()
      event.returnValue = ''
    }
  }

  function stopAutoSave() {
    paused = true
    queued = false
    clearTimeout(timer)
    clearInterval(timer)
    timer = null
  }

  function save() {
    if (disposed) return Promise.resolve(false)
    if (inFlight) {
      queued = true
      return inFlight
    }
    clearTimeout(timer)
    isSaving.value = true
    inFlight = (async () => {
      do {
        queued = false
        const savedRevision = revision
        saveError.value = null
        try {
          const snapshot = JSON.parse(JSON.stringify(toValue(data)))
          await saveFunction(snapshot)
          if (disposed) return false
          lastSaved.value = new Date()
          dirty.value = revision !== savedRevision
          if (!dirty.value) markSaved()
        } catch (error) {
          if (!disposed) {
            saveError.value = error
            dirty.value = true
          }
          return false
        }
      } while (queued && !disposed)
      return true
    })().finally(() => {
      inFlight = null
      if (!disposed) isSaving.value = false
      if (debounce == null) schedule()
    })
    return inFlight
  }

  function schedule() {
    clearTimeout(timer)
    clearInterval(timer)
    timer = null
    if (disposed || paused || !toValue(enabled)) return
    timer = debounce == null
      ? setInterval(() => { if (dirty.value) save() }, interval)
      : setTimeout(() => { if (dirty.value) save() }, debounce)
  }

  function startAutoSave() {
    paused = false
    schedule()
  }

  watch(() => toValue(data), () => {
    revision += 1
    dirty.value = true
    if (toValue(enabled)) retainDraft()
    schedule()
  }, { deep: true, flush: 'sync' })
  watch(() => toValue(enabled), () => schedule())
  onMounted(() => {
    window.addEventListener('beforeunload', beforeUnload)
    startAutoSave()
    if (immediate && toValue(enabled)) save()
  })
  onBeforeUnmount(() => {
    if (dirty.value && (toValue(enabled) || localDraftSaved.value)) retainDraft()
    window.removeEventListener('beforeunload', beforeUnload)
    disposed = true
    stopAutoSave()
  })

  return { isSaving, lastSaved, saveError, dirty, localDraftSaved, draftStorageError,
    retainDraft, restoreDraft, markSaved, save, startAutoSave, stopAutoSave,
    waitForSave: () => inFlight || Promise.resolve(true) }
}
