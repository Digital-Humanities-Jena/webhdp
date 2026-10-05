import { ref, onMounted, onBeforeUnmount, toValue, watch } from 'vue'

export function useAutoSave(saveFunction, data, options = {}) {
  const { interval = 30000, debounce = null, immediate = false, enabled = true } = options
  const isSaving = ref(false)
  const lastSaved = ref(null)
  const saveError = ref(null)
  const dirty = ref(false)
  let timer
  let inFlight = null
  let revision = 0
  let queued = false
  let paused = false
  let disposed = false

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
    schedule()
  }, { deep: true, flush: 'sync' })
  watch(() => toValue(enabled), () => schedule())
  onMounted(() => {
    startAutoSave()
    if (immediate && toValue(enabled)) save()
  })
  onBeforeUnmount(() => {
    disposed = true
    stopAutoSave()
  })

  return { isSaving, lastSaved, saveError, dirty, save, startAutoSave, stopAutoSave,
    waitForSave: () => inFlight || Promise.resolve(true) }
}
