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

it('allows manual saves while automatic scheduling is disabled', async () => {
  const saveFunction = vi.fn().mockResolvedValue(undefined)
  const wrapper = mountAutoSaveHarness(saveFunction, { enabled: false })
  wrapper.vm.data.title = 'Manual draft'
  await nextTick()
  expect(await wrapper.vm.save()).toBe(true)
  expect(saveFunction).toHaveBeenCalledWith({ title: 'Manual draft' })
  wrapper.unmount()
})

it('serializes overlapping saves and takes an immutable snapshot of each revision', async () => {
  let acknowledge
  const saveFunction = vi.fn().mockImplementationOnce(() => new Promise(resolve => { acknowledge = resolve })).mockResolvedValue(undefined)
  const wrapper = mountAutoSaveHarness(saveFunction, { enabled: false })
  const first = wrapper.vm.save()
  wrapper.vm.data.title = 'Newest revision'
  await nextTick()
  const second = wrapper.vm.save()
  expect(saveFunction).toHaveBeenCalledTimes(1)
  expect(saveFunction.mock.calls[0][0].title).toBe('Draft')
  acknowledge()
  await Promise.all([first, second])
  expect(saveFunction).toHaveBeenCalledTimes(2)
  expect(saveFunction.mock.calls[1][0].title).toBe('Newest revision')
  expect(wrapper.vm.dirty).toBe(false)
  wrapper.unmount()
})

it('keeps failed edits unsaved until a successful retry', async () => {
  const saveFunction = vi.fn().mockRejectedValueOnce(new Error('network unavailable')).mockResolvedValue(undefined)
  const wrapper = mountAutoSaveHarness(saveFunction, { enabled: false })
  expect(await wrapper.vm.save()).toBe(false)
  expect(wrapper.vm.lastSaved).toBe(null)
  expect(wrapper.vm.dirty).toBe(true)
  expect(await wrapper.vm.save()).toBe(true)
  expect(wrapper.vm.saveError).toBe(null)
  expect(wrapper.vm.dirty).toBe(false)
  wrapper.unmount()
})

it('debounces edits on a reactive object and cancels the pending save on unmount', async () => {
  vi.useFakeTimers()
  const { reactive } = await import('vue')
  const saveFunction = vi.fn().mockResolvedValue(undefined)
  const wrapper = mount(defineComponent({
    setup() { const data = reactive({ title: 'Draft' }); return { data, ...useAutoSave(saveFunction, data, { debounce: 3000 }) } },
    template: '<div />',
  }))
  wrapper.vm.data.title = 'First edit'
  await nextTick()
  await vi.advanceTimersByTimeAsync(2000)
  wrapper.vm.data.title = 'Final edit'
  await nextTick()
  await vi.advanceTimersByTimeAsync(2999)
  expect(saveFunction).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(1)
  expect(saveFunction).toHaveBeenCalledWith({ title: 'Final edit' })
  wrapper.vm.data.title = 'Abandoned edit'
  await nextTick()
  wrapper.unmount()
  await vi.advanceTimersByTimeAsync(3000)
  expect(saveFunction).toHaveBeenCalledTimes(1)
})
