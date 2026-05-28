import { defineConfig, mergeConfig } from 'vitest/config'

import viteConfig from './vite.config'

export default mergeConfig(viteConfig, defineConfig({
  test: {
    environment: 'jsdom',
    environmentOptions: {
      jsdom: {
        url: 'http://localhost/'
      }
    },
    include: ['tests/**/*.spec.mjs', 'tests/**/*.test.mjs'],
    setupFiles: ['./tests/setup.vitest.mjs'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      reportsDirectory: './coverage',
      include: [
        'src/stores/auth.js',
        'src/stores/system.js',
        'src/stores/workflow.js',
        'src/composables/useAutoSave.js',
        'src/composables/useToast.js',
        'src/services/api.js',
        'src/services/apiBase.js',
        'src/utils/workflowState.js'
      ],
      exclude: ['src/main.js'],
      thresholds: {
        lines: 85,
        functions: 85,
        statements: 85,
        branches: 75
      }
    }
  }
}))
