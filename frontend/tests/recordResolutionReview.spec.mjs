import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import RecordResolutionReview from '../src/components/workflow/RecordResolutionReview.vue'

const buildAnalysis = () => ({
  policy_preset: 'balanced',
  state: {
    policy_override: 'balanced',
    decisions: [],
  },
  summary: {
    candidate_count: 2,
    clean: 0,
    warning: 1,
    version: 1,
    blocker: 0,
    resolved_count: 0,
    unresolved_count: 2,
    can_continue: false,
  },
  candidates: [
    {
      decision_key: 'dataset::model-a',
      candidate_filename: 'model-a.glb',
      candidate_source_file: '/tmp/dataset/model-a.glb',
      normalized_source_file_path: 'dataset/model-a.glb',
      severity: 'version',
      recommended_action: 'create_version',
      selected_action: 'create_version',
      allowed_actions: ['create_version', 'skip'],
      confidence: { label: 'high', score: 1 },
      explanation: 'Same-lineage exact path match.',
      matched_record_count: 1,
      matched_records: [
        {
          session_id: 7,
          local_record_id: 11,
          record_title: 'Model A',
          record_status: 'published',
          concept_rec_id: '7001',
          source_sha256_hash: 'hash-a',
        },
      ],
      recommended_target: {
        session_id: 7,
        local_record_id: 11,
        record_title: 'Model A',
        concept_rec_id: '7001',
      },
      selected_target: {
        session_id: 7,
        local_record_id: 11,
        record_title: 'Model A',
        concept_rec_id: '7001',
      },
      reason_codes: ['exact_path_same_lineage'],
      evidence: { hard_rule: { rule: 'exact_path_same_lineage' } },
      resolved: false,
    },
    {
      decision_key: 'dataset::model-b',
      candidate_filename: 'model-b.glb',
      candidate_source_file: '/tmp/dataset/model-b.glb',
      normalized_source_file_path: 'dataset/model-b.glb',
      severity: 'warning',
      recommended_action: 'create_fresh_record',
      selected_action: 'create_fresh_record',
      allowed_actions: ['create_fresh_record', 'force_create_fresh', 'skip'],
      confidence: { label: 'medium', score: 0.58 },
      explanation: 'Secondary identity signals overlap.',
      matched_record_count: 1,
      matched_records: [
        {
          session_id: 9,
          local_record_id: 15,
          record_title: 'Model B',
          record_status: 'published',
          concept_rec_id: '7009',
          source_sha256_hash: 'hash-b',
        },
      ],
      recommended_target: null,
      selected_target: null,
      reason_codes: ['hash_match'],
      evidence: { soft_match: { matched_record_count: 1 } },
      resolved: false,
    },
  ],
})

describe('RecordResolutionReview', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders affected candidates and emits saved decisions on action changes', async () => {
    const wrapper = mount(RecordResolutionReview, {
      props: {
        analysis: buildAnalysis(),
      },
    })

    expect(wrapper.text()).toContain('model-a.glb')
    expect(wrapper.text()).toContain('model-b.glb')
    expect(wrapper.text()).toContain('Same-lineage exact path match.')

    const selects = wrapper.findAll('select')
    await selects[2].setValue('skip')
    await flushPromises()

    const saveEvents = wrapper.emitted('save-decisions')
    expect(saveEvents).toBeTruthy()
    expect(saveEvents.at(-1)[0]).toMatchObject({
      policy_override: 'balanced',
    })
    expect(saveEvents.at(-1)[0].decisions).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          decision_key: 'dataset::model-b',
          action: 'skip',
          resolved: true,
        }),
      ])
    )
  })

  it('shows a reasoning modal with evidence and matched records', async () => {
    const wrapper = mount(RecordResolutionReview, {
      props: {
        analysis: buildAnalysis(),
      },
      attachTo: document.body,
    })

    const explainButton = wrapper.findAll('button').find((button) => button.text() === 'Explain')
    await explainButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Decision summary')
    expect(wrapper.text()).toContain('Matched records')
    expect(wrapper.text()).toContain('hash-a')
    expect(wrapper.text()).toContain('exact_path_same_lineage')
  })

  it('requires explicit confirmation and a reason before force-create is saved', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const promptSpy = vi.spyOn(window, 'prompt').mockReturnValue('')

    const wrapper = mount(RecordResolutionReview, {
      props: {
        analysis: buildAnalysis(),
      },
    })

    const selects = wrapper.findAll('select')
    await selects[2].setValue('force_create_fresh')
    await flushPromises()

    expect(confirmSpy).toHaveBeenCalled()
    expect(promptSpy).not.toHaveBeenCalled()
    expect(wrapper.emitted('save-decisions')).toBeFalsy()

    confirmSpy.mockReturnValue(true)
    promptSpy.mockReturnValue('Approved by curator')

    await selects[2].setValue('force_create_fresh')
    await flushPromises()

    expect(promptSpy).toHaveBeenCalled()
    const saveEvents = wrapper.emitted('save-decisions')
    expect(saveEvents.at(-1)[0].decisions).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          decision_key: 'dataset::model-b',
          action: 'force_create_fresh',
          forced_override_reason: 'Approved by curator',
        }),
      ])
    )
  })

  it('renders global hash collision matches with Zenodo links', () => {
    const wrapper = mount(RecordResolutionReview, {
      props: {
        analysis: {
          policy_preset: 'balanced',
          summary: {
            candidate_count: 1,
            warning: 1,
            resolved_count: 0,
            unresolved_count: 1,
          },
          candidates: [
            {
              decision_key: 'dataset::model.glb',
              candidate_filename: 'model.glb',
              normalized_source_file_path: 'dataset/model.glb',
              severity: 'warning',
              recommended_action: 'create_fresh_record',
              selected_action: 'create_fresh_record',
              allowed_actions: ['create_fresh_record', 'skip'],
              confidence: { label: 'medium', score: 0.35 },
              explanation: 'This file has the same content hash as an existing Zenodo record.',
              matched_record_count: 1,
              matched_records: [
                {
                  session_id: 7,
                  local_record_id: 21,
                  record_title: 'Existing Model',
                  record_status: 'published',
                  environment: 'production',
                  zenodo_doi: '10.5281/zenodo.9001',
                  record_link: 'https://zenodo.org/records/9001',
                },
              ],
              reason_codes: ['global_hash_collision'],
              evidence: {},
              resolved: false,
            },
          ],
        },
      },
    })

    expect(wrapper.text()).toContain('Colliding Zenodo records')
    expect(wrapper.text()).toContain('Existing Model')
    expect(wrapper.text()).toContain('10.5281/zenodo.9001')
    const links = wrapper.findAll('a[href="https://zenodo.org/records/9001"]')
    expect(links.length).toBeGreaterThan(0)
    expect(links[0].attributes('target')).toBe('_blank')
    expect(links[0].attributes('rel')).toContain('noopener')
  })

  it('shows hidden collision counts for matches outside visible scope', () => {
    const wrapper = mount(RecordResolutionReview, {
      props: {
        analysis: {
          candidates: [
            {
              decision_key: 'dataset::model.glb',
              candidate_filename: 'model.glb',
              normalized_source_file_path: 'dataset/model.glb',
              severity: 'warning',
              recommended_action: 'create_fresh_record',
              selected_action: 'create_fresh_record',
              allowed_actions: ['create_fresh_record', 'skip'],
              confidence: { label: 'medium', score: 0.35 },
              explanation: 'Hidden collision.',
              matched_record_count: 2,
              matched_records: [],
              hidden_matched_record_count: 2,
              reason_codes: ['global_hash_collision'],
              evidence: {},
              resolved: false,
            },
          ],
          summary: {},
        },
      },
    })

    expect(wrapper.text()).toContain('2 hidden matches')
  })
})
