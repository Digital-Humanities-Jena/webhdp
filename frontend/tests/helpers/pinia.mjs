import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

export function activateTestPinia() {
  const pinia = createPinia()
  setActivePinia(pinia)
  return pinia
}

export function mountWithPinia(component, options = {}) {
  const pinia = options.pinia ?? activateTestPinia()
  const plugins = options.global?.plugins ? [...options.global.plugins] : []

  if (!plugins.includes(pinia)) {
    plugins.push(pinia)
  }

  return {
    pinia,
    wrapper: mount(component, {
      ...options,
      global: {
        ...options.global,
        plugins,
      },
    }),
  }
}
