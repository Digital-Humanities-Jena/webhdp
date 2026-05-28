import { beforeEach, describe, expect, it, vi } from 'vitest'

describe('useToast', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.useFakeTimers()
  })

  it('adds and automatically removes timed toasts', async () => {
    const { useToast } = await import('../src/composables/useToast.js')
    const toast = useToast()

    toast.success('Saved', 1000)
    expect(toast.toasts.value).toHaveLength(1)
    expect(toast.toasts.value[0]).toMatchObject({
      message: 'Saved',
      variant: 'success',
    })

    await vi.advanceTimersByTimeAsync(1000)
    expect(toast.toasts.value).toHaveLength(0)
  })

  it('removes persistent toasts manually', async () => {
    const { useToast } = await import('../src/composables/useToast.js')
    const toast = useToast()

    const toastId = toast.warning('Check this', 0)
    expect(toast.toasts.value).toHaveLength(1)

    toast.removeToast(toastId)
    expect(toast.toasts.value).toHaveLength(0)
  })
})
