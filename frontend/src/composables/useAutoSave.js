import { ref, onMounted, onUnmounted, watch } from 'vue'

export function useAutoSave(saveFunction, data, options = {}) {
  const {
    interval = 30000, // 30 seconds
    immediate = false,
    enabled = true
  } = options

  const isSaving = ref(false)
  const lastSaved = ref(null)
  const saveError = ref(null)
  let intervalId = null

  const save = async () => {
    if (!enabled || isSaving.value) return

    isSaving.value = true
    saveError.value = null

    try {
      await saveFunction(data.value)
      lastSaved.value = new Date()
    } catch (error) {
      console.error('Auto-save failed:', error)
      saveError.value = error
    } finally {
      isSaving.value = false
    }
  }

  const startAutoSave = () => {
    if (intervalId) return

    if (immediate) save()

    intervalId = setInterval(save, interval)
  }

  const stopAutoSave = () => {
    if (intervalId) {
      clearInterval(intervalId)
      intervalId = null
    }
  }

  // Watch for data changes to trigger save
  watch(data, () => {
    // Debounced save on change
    if (enabled) {
      stopAutoSave()
      startAutoSave()
    }
  }, { deep: true })

  onMounted(() => {
    if (enabled) startAutoSave()
  })

  onUnmounted(() => {
    stopAutoSave()
  })

  return {
    isSaving,
    lastSaved,
    saveError,
    save,
    startAutoSave,
    stopAutoSave
  }
}
