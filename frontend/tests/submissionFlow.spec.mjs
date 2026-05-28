import { describe, expect, it } from 'vitest'

import {
  applyTerminalProgressState,
  deriveSubmissionPlan,
  resolveRecordResolutionSelections,
} from '../src/utils/submissionFlow.js'

describe('submissionFlow helpers', () => {
  it('describes first-submit selections as record creation during submit', () => {
    const plan = deriveSubmissionPlan({ selectedCount: 3, existingRecordIds: [] })

    expect(plan.mode).toBe('create_records')
    expect(plan.recordsToCreateCount).toBe(3)
    expect(plan.description).toContain('create 3 local records')
  })

  it('describes full canonical matches as record reuse', () => {
    const plan = deriveSubmissionPlan({ selectedCount: 2, existingRecordIds: [11, 12] })

    expect(plan.mode).toBe('reprocess_records')
    expect(plan.recordsToCreateCount).toBe(0)
    expect(plan.successSummary).toContain('reused for reprocessing')
  })

  it('describes mixed record-resolution execution plans', () => {
    const plan = deriveSubmissionPlan({
      selectedCount: 3,
      executionItems: [
        { action: 'create_version' },
        { action: 'create_fresh_record' },
        { action: 'skip' },
      ],
    })

    expect(plan.mode).toBe('record_resolution_plan')
    expect(plan.description).toContain('create version draft')
    expect(plan.description).toContain('create fresh record')
    expect(plan.description).toContain('will be skipped')
  })

  it('resolves selected files against saved record-resolution candidates', () => {
    const result = resolveRecordResolutionSelections({
      selectedFiles: [
        { absolute_path: '/tmp/dataset/model-a.glb', filename: 'model-a.glb' },
        { absolute_path: '/tmp/dataset/model-b.glb', filename: 'model-b.glb' },
      ],
      candidates: [
        {
          decision_key: 'dataset::model-a',
          candidate_source_file: '/tmp/dataset/model-a.glb',
          candidate_filename: 'model-a.glb',
          normalized_source_file_path: 'dataset/model-a.glb',
          severity: 'version',
          resolved: true,
          selected_action: 'create_version',
          selected_target: {
            session_id: 7,
            local_record_id: 11,
            concept_rec_id: '7001',
          },
        },
        {
          decision_key: 'dataset::model-b',
          candidate_source_file: '/tmp/dataset/model-b.glb',
          candidate_filename: 'model-b.glb',
          normalized_source_file_path: 'dataset/model-b.glb',
          severity: 'warning',
          resolved: true,
          selected_action: 'skip',
        },
      ],
    })

    expect(result.executionItems).toHaveLength(2)
    expect(result.executionItems[0]).toMatchObject({
      decision_key: 'dataset::model-a',
      action: 'create_version',
      target_session_id: 7,
      target_local_record_id: 11,
      target_concept_rec_id: '7001',
    })
    expect(result.executionItems[1]).toMatchObject({
      decision_key: 'dataset::model-b',
      action: 'skip',
    })
    expect(result.unresolvedCandidates).toHaveLength(0)
    expect(result.unmatchedSelections).toHaveLength(0)
  })

  it('forces terminal progress to failed even when the last progress stage looked completed', () => {
    const progress = applyTerminalProgressState(
      { current_stage: 'completed', status_message: 'Record completed' },
      'failed',
      'LOD generation failed',
    )

    expect(progress.current_stage).toBe('failed')
    expect(progress.status_message).toBe('LOD generation failed')
  })
})
