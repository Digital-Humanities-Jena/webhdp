import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/services/pipeline.service', () => ({
  default: {
    getPlaygroundSessionFile: vi.fn(),
  },
}))

import PlaygroundFileListFieldWidget from '../src/components/tools/playground/PlaygroundFileListFieldWidget.vue'
import PlaygroundPathFieldWidget from '../src/components/tools/playground/PlaygroundPathFieldWidget.vue'

describe('Playground session path widgets', () => {
  it('filters session file suggestions and applies a selected file path', async () => {
    const wrapper = mount(PlaygroundPathFieldWidget, {
      props: {
        field: {
          name: 'input_file',
          label: 'Input File',
          widget: 'file_picker',
          path_source: 'files',
          accept_extensions: ['.glb'],
        },
        modelValue: '',
        suggestedFiles: ['/tmp/assets/a.glb', '/tmp/assets/b.ply', '/tmp/assets/c.glb'],
      },
    })

    const pathButtons = wrapper.findAll('[data-testid^="session-path-input_file-item-"]')
    expect(pathButtons).toHaveLength(2)

    await wrapper.get('[data-testid="session-path-input_file-search"]').setValue('c.glb')
    await wrapper.get('[data-testid="session-path-input_file-item-0"]').trigger('click')

    expect(wrapper.emitted('update:modelValue')).toEqual([['/tmp/assets/c.glb']])
  })

  it('supports append and replace bulk actions for manifest-backed file lists', async () => {
    const wrapper = mount(PlaygroundFileListFieldWidget, {
      props: {
        field: {
          name: 'input_files',
          label: 'Input Files',
          widget: 'file_list_picker',
          accept_extensions: ['.glb'],
        },
        modelValue: '/tmp/existing.glb',
        suggestedFiles: ['/tmp/assets/a.glb', '/tmp/assets/b.glb', '/tmp/assets/c.ply'],
      },
    })

    await wrapper.get('[data-testid="session-file-list-input_files-bulk-append_all_matching"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')[0]).toEqual([
      '/tmp/existing.glb\n/tmp/assets/a.glb\n/tmp/assets/b.glb',
    ])

    await wrapper.get('[data-testid="session-file-list-input_files-search"]').setValue('b.glb')
    await wrapper.get('[data-testid="session-file-list-input_files-bulk-replace_all_matching"]').trigger('click')

    expect(wrapper.emitted('update:modelValue')[1]).toEqual(['/tmp/assets/b.glb'])
  })
})
