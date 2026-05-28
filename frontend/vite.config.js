import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { createHash } from 'node:crypto'

function manualVendorChunks(id) {
  const normalizedId = id.split('\\').join('/')

  if (!normalizedId.includes('/node_modules/')) {
    return undefined
  }

  if (normalizedId.includes('/node_modules/three/examples/')) {
    return 'vendor-three-examples'
  }
  if (normalizedId.includes('/node_modules/three/')) {
    return 'vendor-three-core'
  }
  if (normalizedId.includes('/node_modules/@google/model-viewer/')) {
    return 'vendor-model-viewer'
  }
  if (normalizedId.includes('/node_modules/lit/') || normalizedId.includes('/node_modules/@lit/')) {
    return 'vendor-lit'
  }
  if (normalizedId.includes('/node_modules/@monogrid/gainmap-js/')) {
    return 'vendor-gainmap'
  }
  if (normalizedId.includes('/node_modules/cytoscape-cose-bilkent/')) {
    return 'vendor-cytoscape-cose-bilkent'
  }
  if (normalizedId.includes('/node_modules/cytoscape-fcose/')) {
    return 'vendor-cytoscape-fcose'
  }
  if (normalizedId.includes('/node_modules/cose-base/') || normalizedId.includes('/node_modules/layout-base/')) {
    return 'vendor-cytoscape-layout'
  }
  if (normalizedId.includes('/node_modules/cytoscape/')) {
    return 'vendor-cytoscape-core'
  }
  if (normalizedId.includes('/node_modules/katex/')) {
    return 'vendor-katex'
  }
  if (normalizedId.includes('/node_modules/marked/') || normalizedId.includes('/node_modules/dompurify/')) {
    return 'vendor-docs-markdown'
  }

  return undefined
}

function webhdpPwaPrecachePlugin() {
  let precacheAssets = []

  return {
    name: 'webhdp-pwa-precache',
    apply: 'build',
    generateBundle(_, bundle) {
      precacheAssets = Object.keys(bundle)
        .filter((fileName) => fileName.startsWith('assets/'))
        .filter((fileName) => /\.(css|gif|jpe?g|js|png|svg|webp|woff2?)$/i.test(fileName))
        .map((fileName) => `/${fileName}`)
        .sort()
    },
    writeBundle(options) {
      const outputDir = options.dir || fileURLToPath(new URL('./dist', import.meta.url))
      const serviceWorkerPath = join(outputDir, 'sw.js')
      const serviceWorkerSource = readFileSync(serviceWorkerPath, 'utf8')
      const cacheVersion = createHash('sha256')
        .update(precacheAssets.join('\n'))
        .digest('hex')
        .slice(0, 12)
      const patchedSource = serviceWorkerSource
        .replace('__WEBHDP_CACHE_VERSION__', cacheVersion)
        .replace(
          "  '__WEBHDP_PRECACHE_PLACEHOLDER__',",
          precacheAssets.map((assetPath) => `  '${assetPath}',`).join('\n')
        )

      writeFileSync(serviceWorkerPath, patchedSource)
    },
  }
}

export default defineConfig({
  plugins: [
    vue({
      template: {
        compilerOptions: {
          isCustomElement: (tag) => tag === 'model-viewer'
        }
      }
    }),
    webhdpPwaPrecachePlugin(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_PROXY_TARGET || 'http://localhost:5000',
        changeOrigin: true
      }
    }
  },
  build: {
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks: manualVendorChunks,
      },
    },
  }
})
