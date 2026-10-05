import { expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { http } from 'msw'
import FileMetadataView from '../src/views/workflow/FileMetadataView.vue'
import { useWorkflowStore } from '../src/stores/workflow'
import { mountWithApp } from './helpers/app.mjs'
import { activateTestPinia } from './helpers/pinia.mjs'
import { apiV1Url, jsonResponse, readJsonBody } from './msw/http.mjs'
import { server } from './msw/server.mjs'

async function setup(files = [{ file_id: 101, filename: 'model.glb' }]) {
  const pinia = activateTestPinia()
  const workflowStore = useWorkflowStore(pinia)
  workflowStore.setSessionId(42)
  workflowStore.setSelectedFiles(files)
  for (const file of files) {
    server.use(http.get(apiV1Url(`/metadata/file/${file.file_id}`), () => jsonResponse({ data: { metadata: { title: 'Original title' } } })))
  }
  return mountWithApp(FileMetadataView, { pinia, route: '/workflow/files' })
}

it('reports an unsuccessful file draft as unsaved and permits retry', async () => {
  server.use(http.post(apiV1Url('/metadata/file/101'), () => jsonResponse({ error: { message: 'Storage unavailable' } }, { status: 503 })))
  const { wrapper } = await setup()
  vi.useFakeTimers()
  await wrapper.get('input[type="text"]').setValue('Latest title')
  await vi.advanceTimersByTimeAsync(3000)
  await flushPromises()
  expect(wrapper.text()).toContain('Draft save failed')
  expect(wrapper.text()).not.toContain('Last saved:')
  let saved
  server.use(http.post(apiV1Url('/metadata/file/101'), async ({ request }) => {
    saved = await readJsonBody(request)
    return jsonResponse({ data: { saved_fields: 3 } })
  }))
  await wrapper.findAll('button').find(button => button.text() === 'Retry save').trigger('click')
  await flushPromises()
  expect(saved.metadata.title).toBe('Latest title')
  expect(wrapper.text()).toContain('Last saved:')
  wrapper.unmount()
})

it('settles every file draft after a partial failure before starting final saves', async () => {
  let release
  const acknowledged = new Promise(resolve => { release = resolve })
  const saves = { 101: [], 102: [] }
  for (const fileId of [101, 102]) {
    server.use(http.post(apiV1Url(`/metadata/file/${fileId}`), async ({ request }) => {
      const payload = await readJsonBody(request)
      saves[fileId].push(payload)
      if (saves[fileId].length === 1) {
        if (fileId === 101) return jsonResponse({ error: { message: 'Storage unavailable' } }, { status: 503 })
        await acknowledged
      }
      return jsonResponse({ data: { saved_fields: 3 } })
    }))
  }
  const { wrapper, router } = await setup([
    { file_id: 101, filename: 'model.glb' },
    { file_id: 102, filename: 'other.glb' },
  ])
  vi.useFakeTimers()
  await wrapper.get('input[type="text"]').setValue('Draft revision')
  await vi.advanceTimersByTimeAsync(3000)
  await flushPromises()
  await wrapper.get('input[type="text"]').setValue('Final revision')
  await wrapper.findAll('button').find(button => button.text().includes('Save & Continue')).trigger('click')
  await flushPromises()
  expect(saves[101]).toHaveLength(1)
  expect(saves[102]).toHaveLength(1)
  expect(router.currentRoute.value.path).toBe('/workflow/files')
  release()
  await flushPromises()
  expect(saves[101].map(payload => payload.metadata.title)).toEqual(['Draft revision', 'Final revision'])
  expect(saves[102]).toHaveLength(2)
  expect(router.currentRoute.value.path).toBe('/workflow/metadata')
  wrapper.unmount()
})

it('waits for an in-flight draft before committing the latest file metadata', async () => {
  let release
  const acknowledged = new Promise(resolve => { release = resolve })
  const saves = []
  server.use(http.post(apiV1Url('/metadata/file/101'), async ({ request }) => {
    const payload = await readJsonBody(request)
    saves.push(payload)
    if (saves.length === 1) await acknowledged
    return jsonResponse({ data: { saved_fields: 3 } })
  }))
  const { wrapper, router } = await setup()
  vi.useFakeTimers()
  await wrapper.get('input[type="text"]').setValue('Draft revision')
  await vi.advanceTimersByTimeAsync(3000)
  await flushPromises()
  await wrapper.get('input[type="text"]').setValue('Final revision')
  await wrapper.findAll('button').find(button => button.text().includes('Save & Continue')).trigger('click')
  await flushPromises()
  expect(saves).toHaveLength(1)
  expect(router.currentRoute.value.path).toBe('/workflow/files')
  release()
  await flushPromises()
  expect(saves.map(payload => payload.metadata.title)).toEqual(['Draft revision', 'Final revision'])
  expect(router.currentRoute.value.path).toBe('/workflow/metadata')
  await vi.advanceTimersByTimeAsync(6000)
  expect(saves).toHaveLength(2)
  wrapper.unmount()
})
