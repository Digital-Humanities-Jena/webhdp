import pipelineService from '@/services/pipeline.service'
import { usePersistentPipelineRun } from './usePersistentPipelineRun'

export function usePersistentPlaygroundRun(userId, componentKey) {
  return usePersistentPipelineRun(userId, {
    runKind: 'playground',
    storageKey: () => `playground-run:${userId()}:${componentKey()}`,
    execute: async (request, requestId) => {
      const response = await pipelineService.executePlayground({ ...request, request_id: requestId, async_execution: true }, { suppressGlobalError: true })
      const run = response.data?.playground_run
      return { data: { run_id: run.run_id, run } }
    },
    getRun: async (runId) => {
      const response = await pipelineService.getPlaygroundRun(runId)
      return { data: { run: response.data?.playground_run } }
    },
    cancelRun: pipelineService.cancelPlaygroundRun,
  })
}
