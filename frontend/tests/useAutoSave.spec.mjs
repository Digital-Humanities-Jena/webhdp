import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, nextTick, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAutoSave } from '../src/composables/useAutoSave.js'

function mountAutoSaveHarness(saveFunction, options = {}, initialData = { title: 'Draft' }) {
  const Harness = defineComponent({
    setup() {
      const data = ref(initialData)
      return {
        data,
        ...useAutoSave(saveFunction, data, options),
      }
    },
    template: '<div />',
  })

  return mount(Harness)
}

describe('useAutoSave', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  it('saves the latest data after the configured interval', async () => {
    const saveFunction = vi.fn().mockResolvedValue(undefined)
    const wrapper = mountAutoSaveHarness(saveFunction, { interval: 1000 })

    wrapper.vm.data.title = 'Updated draft'
    await nextTick()

    await vi.advanceTimersByTimeAsync(999)
    expect(saveFunction).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()

    expect(saveFunction).toHaveBeenCalledTimes(1)
    expect(saveFunction).toHaveBeenCalledWith({ title: 'Updated draft' })
    expect(wrapper.vm.lastSaved).toBeInstanceOf(Date)
  })

  it('captures save failures and resets the saving state', async () => {
    const saveFunction = vi.fn().mockRejectedValue(new Error('save failed'))
    const wrapper = mountAutoSaveHarness(saveFunction, { immediate: true, interval: 1000 })

    await flushPromises()

    expect(saveFunction).toHaveBeenCalledTimes(1)
    expect(wrapper.vm.isSaving).toBe(false)
    expect(wrapper.vm.saveError).toBeInstanceOf(Error)
    expect(wrapper.vm.saveError.message).toBe('save failed')
  })

  it('stops scheduling saves after the component unmounts', async () => {
    const saveFunction = vi.fn().mockResolvedValue(undefined)
    const wrapper = mountAutoSaveHarness(saveFunction, { interval: 1000 })

    wrapper.vm.data.title = 'Before unmount'
    await nextTick()
    wrapper.unmount()

    await vi.advanceTimersByTimeAsync(1000)

    expect(saveFunction).not.toHaveBeenCalled()
  })

  it('does not schedule saves when auto-save is disabled', async () => {
    const saveFunction = vi.fn().mockResolvedValue(undefined)
    const wrapper = mountAutoSaveHarness(saveFunction, { enabled: false, interval: 1000 })

    wrapper.vm.data.title = 'Ignored'
    await nextTick()
    await vi.advanceTimersByTimeAsync(1000)

    expect(saveFunction).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
