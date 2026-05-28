import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent } from 'vue'

import { activateTestPinia } from './pinia.mjs'

const EmptyRouteComponent = defineComponent({
  name: 'EmptyRouteComponent',
  template: '<div />',
})

export const AlertStub = defineComponent({
  name: 'AlertStub',
  props: {
    message: {
      type: String,
      default: '',
    },
    title: {
      type: String,
      default: '',
    },
  },
  template: `
    <div class="alert-stub">
      <p v-if="title">{{ title }}</p>
      <p v-if="message">{{ message }}</p>
      <slot />
    </div>
  `,
})

export const LoadingSpinnerStub = defineComponent({
  name: 'LoadingSpinnerStub',
  props: {
    text: {
      type: String,
      default: '',
    },
  },
  template: '<div class="loading-spinner-stub">{{ text }}</div>',
})

export const StepIndicatorStub = defineComponent({
  name: 'StepIndicatorStub',
  props: {
    currentStep: {
      type: Number,
      default: null,
    },
  },
  template: '<div class="step-indicator-stub">Step {{ currentStep }}</div>',
})

export function createTestRouter(routes = []) {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: EmptyRouteComponent },
      { path: '/workflow/upload', component: EmptyRouteComponent },
      { path: '/workflow/msf-analysis', component: EmptyRouteComponent },
      { path: '/workflow/files', component: EmptyRouteComponent },
      { path: '/workflow/metadata', component: EmptyRouteComponent },
      { path: '/workflow/edm-selection', component: EmptyRouteComponent },
      { path: '/workflow/pipeline', component: EmptyRouteComponent },
      { path: '/workflow/submit', component: EmptyRouteComponent },
      { path: '/uploads/:id', component: EmptyRouteComponent },
      { path: '/:pathMatch(.*)*', component: EmptyRouteComponent },
      ...routes,
    ],
  })
}

export async function mountWithApp(component, {
  route = '/',
  query = null,
  pinia = activateTestPinia(),
  router = createTestRouter(),
  routes,
  global = {},
  ...options
} = {}) {
  const appRouter = routes ? createTestRouter(routes) : router

  if (query) {
    await appRouter.push({ path: route, query })
  } else {
    await appRouter.push(route)
  }
  await appRouter.isReady()

  const plugins = global.plugins ? [...global.plugins] : []
  if (!plugins.includes(pinia)) {
    plugins.push(pinia)
  }
  if (!plugins.includes(appRouter)) {
    plugins.push(appRouter)
  }

  const wrapper = mount(component, {
    ...options,
    global: {
      ...global,
      plugins,
      stubs: {
        StepIndicator: StepIndicatorStub,
        LoadingSpinner: LoadingSpinnerStub,
        Alert: AlertStub,
        ...global.stubs,
      },
    },
  })

  await flushPromises()

  return {
    wrapper,
    pinia,
    router: appRouter,
  }
}
