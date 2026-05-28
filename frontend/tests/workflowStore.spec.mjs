import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useWorkflowStore } from '../src/stores/workflow.js'
import { activateTestPinia } from './helpers/pinia.mjs'

describe('workflow store', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('hydrates from persisted workflow state', () => {
    sessionStorage.setItem('workflowState', JSON.stringify({
      currentStep: 4,
      sessionId: 21,
      selectedFiles: [{ file_id: 9 }],
      submissionMetadata: { title: 'Persisted title' },
      lodMinimumViablePrefs: { edm: false, iiif: true, mets: false },
    }))
    activateTestPinia()

    const store = useWorkflowStore()

    expect(store.currentStep).toBe(4)
    expect(store.sessionId).toBe(21)
    expect(store.selectedFiles).toEqual([{ file_id: 9 }])
    expect(store.submissionMetadata).toEqual({ title: 'Persisted title' })
    expect(store.lodMinimumViablePrefs).toEqual({ edm: false, iiif: true, mets: false })
  })

  it('falls back to a clean state when persisted JSON is invalid', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    sessionStorage.setItem('workflowState', '{bad json')
    activateTestPinia()

    const store = useWorkflowStore()

    expect(store.currentStep).toBe(1)
    expect(store.sessionId).toBeNull()
    expect(consoleError).toHaveBeenCalled()
    consoleError.mockRestore()
  })

  it('persists workflow changes to sessionStorage', async () => {
    activateTestPinia()
    const store = useWorkflowStore()

    store.setSessionId(33)
    store.setSelectedFiles([{ file_id: 101 }])
    store.setSubmissionMetadata({ title: 'Draft title' })
    await nextTick()

    expect(JSON.parse(sessionStorage.getItem('workflowState'))).toMatchObject({
      sessionId: 33,
      selectedFiles: [{ file_id: 101 }],
      submissionMetadata: { title: 'Draft title' },
    })
  })

  it('clears the persisted workflow when reset', async () => {
    activateTestPinia()
    const store = useWorkflowStore()

    store.setSessionId(12)
    await nextTick()
    expect(sessionStorage.getItem('workflowState')).not.toBeNull()

    store.resetWorkflow()

    expect(store.sessionId).toBeNull()
    expect(store.selectedFiles).toEqual([])
    expect(sessionStorage.getItem('workflowState')).toBeNull()
  })

  it('supports workflow navigation, pipeline selection, and MSF batch metadata', async () => {
    activateTestPinia()
    const store = useWorkflowStore()

    expect(store.canGoBack).toBe(false)
    store.nextStep()
    expect(store.currentStep).toBe(2)
    expect(store.canGoBack).toBe(true)

    store.goToStep(6)
    expect(store.currentStep).toBe(6)
    expect(store.canGoNext).toBe(true)

    store.setPipeline({ identifier: 'render' })
    store.setMsfData(
      '/tmp/source.xlsx',
      { is_valid: true },
      { Title: 'title' },
      { 'model.glb': { title: 'Hello' } },
      { source_file_path: '/tmp/source.xlsx' },
      { sheet_name: 'Sheet1' }
    )
    store.setLodMinimumViablePrefs({ edm: false, iiif: true, mets: false })
    store.addFileMetadata('file-1', { creator: 'Museum' })
    store.setUserMetadata({ rights: 'cc-by' })
    await nextTick()

    expect(store.selectedPipeline).toEqual({ identifier: 'render' })
    expect(store.isBatchMode).toBe(true)
    expect(store.msfPath).toBe('/tmp/source.xlsx')
    expect(store.msfValidation).toEqual({ is_valid: true })
    expect(store.msfMapping).toEqual({ Title: 'title' })
    expect(store.fileMetadataMap).toEqual({ 'model.glb': { title: 'Hello' } })
    expect(store.msfProfile).toEqual({ source_file_path: '/tmp/source.xlsx' })
    expect(store.msfParseOptions).toEqual({ sheet_name: 'Sheet1' })
    expect(store.lodMinimumViablePrefs).toEqual({ edm: false, iiif: true, mets: false })
    expect(store.fileMetadata).toEqual({ 'file-1': { creator: 'Museum' } })
    expect(store.userMetadata).toEqual({ rights: 'cc-by' })
    expect(JSON.parse(sessionStorage.getItem('workflowState'))).toMatchObject({
      selectedPipeline: { identifier: 'render' },
      msfPath: '/tmp/source.xlsx',
      isBatchMode: true,
    })
  })

  it('guards invalid navigation and applies default MSF preference branches', async () => {
    activateTestPinia()
    const store = useWorkflowStore()

    store.prevStep()
    expect(store.currentStep).toBe(1)

    store.goToStep(99)
    expect(store.currentStep).toBe(1)

    store.setSelectedFiles(null)
    expect(store.selectedFiles).toEqual([])

    store.goToStep(store.totalSteps)
    store.nextStep()
    expect(store.currentStep).toBe(store.totalSteps)

    store.setMsfData('/tmp/source.xlsx', { is_valid: true }, {}, {}, { parse_options: { delimiter: ';' } })
    store.setMsfPath('')
    store.setLodMinimumViablePrefs({})
    await nextTick()

    expect(store.msfParseOptions).toEqual({ delimiter: ';' })
    expect(store.msfPath).toBeNull()
    expect(store.lodMinimumViablePrefs).toEqual({ edm: true, iiif: true, mets: true })
  })
})
