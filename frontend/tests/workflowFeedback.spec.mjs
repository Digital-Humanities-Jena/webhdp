import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ProgressBar from '../src/components/ui/ProgressBar.vue'
import StepIndicator from '../src/components/workflow/StepIndicator.vue'
import LoadingSpinner from '../src/components/ui/LoadingSpinner.vue'

describe('Workflow feedback', () => {
  it('exposes unknown progress without inventing a percentage', async () => {
    const wrapper = mount(ProgressBar, { props: { label: 'Preparing files' } })
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBeUndefined()
    expect(wrapper.text()).not.toContain('%')
    await wrapper.setProps({ percentage: 42.4 })
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('42')
    expect(wrapper.text()).toContain('42%')
    await wrapper.setProps({ percentage: NaN })
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBeUndefined()
  })

  it.each([[-10, '0'], [120, '100'], [0, '0']])('keeps measured progress %s in a valid range', (percentage, value) => {
    const wrapper = mount(ProgressBar, { props: { percentage, label: 'Upload' } })
    expect(wrapper.get('[role="progressbar"]').attributes('aria-valuenow')).toBe(value)
    expect(wrapper.get('[role="progressbar"]').attributes('aria-label')).toBe('Upload')
  })

  it('identifies the current step without claiming skipped steps are completed', () => {
    const wrapper = mount(StepIndicator, { props: { currentStep: 3 } })
    expect(wrapper.findAll('[aria-current="step"]')).toHaveLength(1)
    expect(wrapper.get('[aria-current="step"]').text()).toContain('Review Files')
    expect(wrapper.text()).toContain('Step 3 of 7')
    expect(wrapper.text()).not.toContain('completed')
  })

  it('names a spinner even when no visual label was requested', () => {
    const wrapper = mount(LoadingSpinner)
    expect(wrapper.get('[role="status"]').text()).toBe('Loading…')
  })
})
