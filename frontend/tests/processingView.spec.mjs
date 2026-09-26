import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocked = vi.hoisted(() => ({
  router: {
    push: vi.fn(),
    replace: vi.fn(),
  },
  route: {
    query: {
      sessionId: '42',
      submissionId: '13',
      runId: 'run-native-42',
      resume: 'workflow',
    },
  },
  workflowStore: {
    sessionId: 42,
  },
  workflowState: {
    restoreWorkflowContext: vi.fn().mockResolvedValue({}),
    shouldRestoreWorkflowContext: vi.fn(() => false),
  },
}))

vi.mock('vue-router', async () => {
  const actual = await vi.importActual('vue-router')
  return {
    ...actual,
    useRoute: () => mocked.route,
    useRouter: () => mocked.router,
  }
})
vi.mock('@/stores/workflow', () => ({
  useWorkflowStore: () => mocked.workflowStore,
}))
vi.mock('@/utils/workflowState', () => ({
  buildWorkflowResumeLocation: (sessionId, workflowHint = {}, fallbackPath = '/workflow/upload') => ({
    path: workflowHint?.resume_route || fallbackPath,
    query: {
      sessionId: String(sessionId),
      resume: 'workflow',
      ...(workflowHint?.submission_id ? { submissionId: String(workflowHint.submission_id) } : {}),
      ...(workflowHint?.pipeline_run_id ? { runId: String(workflowHint.pipeline_run_id) } : {}),
    },
  }),
  restoreWorkflowContext: mocked.workflowState.restoreWorkflowContext,
  shouldRestoreWorkflowContext: mocked.workflowState.shouldRestoreWorkflowContext,
}))

import ProcessingView from '../src/views/workflow/ProcessingView.vue'

describe('ProcessingView', () => {
  beforeEach(() => {
    mocked.router.push.mockReset()
    mocked.router.replace.mockReset()
    mocked.workflowState.restoreWorkflowContext.mockReset().mockResolvedValue({})
    mocked.route.query = { sessionId: '42', submissionId: '13', runId: 'run-native-42', resume: 'workflow' }
    mocked.workflowStore.sessionId = 42
    mocked.workflowState.shouldRestoreWorkflowContext.mockReturnValue(false)
  })

  it('acts as a real handoff page instead of auto-redirecting away', async () => {
    const wrapper = mount(ProcessingView)
    await flushPromises()

    expect(wrapper.text()).toContain('Continue monitoring your submission')
    expect(mocked.router.replace).not.toHaveBeenCalled()

    const button = wrapper.findAll('button').find((item) => item.text() === 'Open Submission Monitor')
    await button.trigger('click')

    expect(mocked.router.push).toHaveBeenCalledWith({
      path: '/workflow/submit',
      query: {
        sessionId: '42',
        resume: 'workflow',
        submissionId: '13',
        runId: 'run-native-42',
      },
    })
  })
  it('keeps the monitor unavailable until restoring a saved session succeeds', async () => {
    mocked.workflowState.shouldRestoreWorkflowContext.mockReturnValue(true)
    mocked.workflowState.restoreWorkflowContext.mockRejectedValueOnce(new Error('Offline'))
    const wrapper = mount(ProcessingView)
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('Could not load this submission')
    const monitor = wrapper.findAll('button').find(button => button.text() === 'Open Submission Monitor')
    expect(monitor.element.disabled).toBe(true)
    await wrapper.findAll('button').find(button => button.text() === 'Try again').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(monitor.element.disabled).toBe(false)
  })

  it('directs an empty resume link to the dashboard instead of an invalid monitor', async () => {
    mocked.route.query = {}
    mocked.workflowStore.sessionId = null
    const wrapper = mount(ProcessingView)
    await flushPromises()
    expect(wrapper.text()).toContain('No submission is selected')
    expect(wrapper.findAll('button').map(button => button.text())).toEqual(['Go to Dashboard'])
  })

})
