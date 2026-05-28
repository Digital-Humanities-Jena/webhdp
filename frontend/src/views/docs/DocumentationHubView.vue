<template>
  <div class="min-h-screen bg-slate-100">
    <header class="bg-gradient-to-r from-sky-700 via-indigo-700 to-cyan-600 text-white">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div class="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p class="inline-flex items-center rounded-full bg-white/15 px-3 py-1 text-xs font-semibold tracking-wider uppercase">
              Documentation Center
            </p>
            <h1 class="mt-3 text-3xl sm:text-4xl font-bold tracking-tight">
              WebHDP Documentation & Guides
            </h1>
            <p class="mt-3 text-sm sm:text-base text-sky-100 max-w-3xl">
              Browse architecture, API references, operations runbooks, and release walkthroughs from one place.
            </p>
          </div>

          <div class="flex items-center gap-3">
            <router-link
              v-if="authStore.isAuthenticated"
              to="/dashboard"
              class="inline-flex items-center rounded-lg bg-white/15 px-4 py-2 text-sm font-semibold text-white hover:bg-white/25 transition-colors"
            >
              Back to Dashboard
            </router-link>
            <router-link
              v-else
              to="/login"
              class="inline-flex items-center rounded-lg bg-white text-sky-700 px-4 py-2 text-sm font-semibold hover:bg-sky-50 transition-colors"
            >
              Sign in
            </router-link>
          </div>
        </div>

        <div class="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div class="rounded-xl border border-white/20 bg-white/10 px-4 py-3">
            <p class="text-xs uppercase tracking-wider text-sky-100">Documents</p>
            <p class="mt-1 text-2xl font-bold text-white">{{ documents.length }}</p>
          </div>
          <div class="rounded-xl border border-white/20 bg-white/10 px-4 py-3">
            <p class="text-xs uppercase tracking-wider text-sky-100">Categories</p>
            <p class="mt-1 text-2xl font-bold text-white">{{ categoryOptions.length }}</p>
          </div>
          <div class="rounded-xl border border-white/20 bg-white/10 px-4 py-3">
            <p class="text-xs uppercase tracking-wider text-sky-100">Active Doc</p>
            <p class="mt-1 text-base font-semibold text-white truncate">{{ activeDocument?.title || 'None' }}</p>
          </div>
        </div>
      </div>
    </header>

    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 -mt-2">
      <div class="grid grid-cols-1 xl:grid-cols-[340px,1fr] gap-6">
        <aside class="rounded-2xl bg-white shadow-sm border border-slate-200 p-4 h-fit">
          <div class="mb-4">
            <label for="docs-search" class="block text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">
              Search
            </label>
            <input
              id="docs-search"
              v-model="searchQuery"
              type="text"
              placeholder="Search title or description"
              class="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500"
            />
          </div>

          <div class="mb-4">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">Audience</p>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="audience in ['all', ...audienceOptions]"
                :key="audience"
                type="button"
                :data-testid="`docs-audience-${audience}`"
                :aria-pressed="selectedAudience === audience"
                @click="selectedAudience = audience"
                :class="[
                  'rounded-full px-3 py-1.5 text-xs font-semibold transition-colors',
                  selectedAudience === audience
                    ? 'bg-emerald-100 text-emerald-700 border border-emerald-200'
                    : 'bg-slate-100 text-slate-600 border border-slate-200 hover:bg-slate-200'
                ]"
              >
                {{ formatAudience(audience) }}
              </button>
            </div>
          </div>

          <div class="mb-4">
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-500 mb-2">Category</p>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="category in ['all', ...categoryOptions]"
                :key="category"
                type="button"
                :data-testid="`docs-category-${category}`"
                :aria-pressed="selectedCategory === category"
                @click="selectedCategory = category"
                :class="[
                  'rounded-full px-3 py-1.5 text-xs font-semibold transition-colors',
                  selectedCategory === category
                    ? 'bg-sky-100 text-sky-700 border border-sky-200'
                    : 'bg-slate-100 text-slate-600 border border-slate-200 hover:bg-slate-200'
                ]"
              >
                {{ formatCategory(category) }}
              </button>
            </div>
          </div>

          <div class="space-y-4 max-h-[68vh] overflow-auto pr-1">
            <div v-for="group in groupedFilteredDocuments" :key="group.category" class="space-y-2">
              <p class="px-1 text-[11px] font-bold uppercase tracking-wide text-slate-500">
                {{ formatCategory(group.category) }}
              </p>
              <button
                v-for="doc in group.documents"
                :key="doc.id"
                type="button"
                :aria-current="activeDocument?.id === doc.id ? 'page' : undefined"
                @click="openDocument(doc)"
                :class="[
                  'w-full text-left rounded-xl border p-3 transition-all',
                  activeDocument?.id === doc.id
                    ? 'border-sky-300 bg-sky-50 shadow-sm'
                    : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'
                ]"
              >
                <div class="flex items-start justify-between gap-3">
                  <p class="text-sm font-semibold text-slate-800 leading-snug">{{ doc.title }}</p>
                  <span class="rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-slate-600">
                    {{ formatAudience(doc.audience) }}
                  </span>
                </div>
                <p class="mt-1 text-xs text-slate-500 line-clamp-2">{{ doc.description }}</p>
              </button>
            </div>

            <p v-if="!filteredDocuments.length && !loadingIndex" class="text-sm text-slate-500 py-6 text-center">
              No documents match your filters.
            </p>
          </div>
        </aside>

        <section class="rounded-2xl bg-white shadow-sm border border-slate-200 min-h-[65vh]">
          <div class="border-b border-slate-200 px-5 py-4 sm:px-7 sm:py-5">
            <div v-if="activeDocument" class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h2 class="text-2xl font-bold text-slate-900">{{ activeDocument.title }}</h2>
                <p class="mt-1 text-sm text-slate-600 max-w-3xl">{{ activeDocument.description }}</p>
              </div>
              <div class="flex flex-wrap items-center gap-2">
                <span class="rounded-full bg-indigo-50 border border-indigo-100 px-3 py-1 text-xs font-semibold text-indigo-700">
                  {{ formatCategory(activeDocument.category) }}
                </span>
                <span class="rounded-full bg-emerald-50 border border-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700">
                  {{ formatAudience(activeDocument.audience) }}
                </span>
                <span v-if="activeDocument.estimated_read_time_min" class="rounded-full bg-slate-100 border border-slate-200 px-3 py-1 text-xs font-semibold text-slate-600">
                  {{ activeDocument.estimated_read_time_min }} min read
                </span>
              </div>
            </div>
            <p v-else class="text-sm text-slate-500">Select a document to start reading.</p>
          </div>

          <div class="px-5 py-5 sm:px-7 sm:py-6">
            <div v-if="loadingIndex || loadingDocument" class="space-y-3 animate-pulse">
              <div class="h-4 bg-slate-200 rounded w-3/4"></div>
              <div class="h-4 bg-slate-200 rounded w-5/6"></div>
              <div class="h-4 bg-slate-200 rounded w-2/3"></div>
              <div class="h-32 bg-slate-200 rounded mt-4"></div>
              <div class="h-4 bg-slate-200 rounded w-4/5"></div>
              <div class="h-4 bg-slate-200 rounded w-2/3"></div>
            </div>

            <div v-else-if="loadError" class="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {{ loadError }}
            </div>

            <article
              v-else-if="renderedHtml"
              class="doc-markdown"
              v-html="renderedHtml"
              @click="handleMarkdownClick"
            ></article>

            <p v-else class="text-sm text-slate-500">No document content available.</p>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import docsService from '@/services/docs.service'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const documents = ref([])
const documentCache = ref({})
const activeDocument = ref(null)

const loadingIndex = ref(false)
const loadingDocument = ref(false)
const loadError = ref('')

const searchQuery = ref('')
const selectedAudience = ref('all')
const selectedCategory = ref('all')
let mermaidModule = null
let mermaidModulePromise = null
let mermaidRenderToken = 0

const audienceOrder = ['beginner', 'user', 'operator', 'developer', 'all']
const categoryOrder = ['start-here', 'workflows', 'account-security', 'reference', 'operations', 'development', 'video-guides']

// Configure marked options
marked.setOptions({
  gfm: true,
  breaks: false
})

const categoryOptions = computed(() => {
  const unique = new Set(documents.value.map(doc => doc.category).filter(Boolean))
  return Array.from(unique).sort((left, right) => {
    const leftIndex = categoryOrder.indexOf(left)
    const rightIndex = categoryOrder.indexOf(right)
    if (leftIndex !== -1 || rightIndex !== -1) {
      return (leftIndex === -1 ? 999 : leftIndex) - (rightIndex === -1 ? 999 : rightIndex)
    }
    return left.localeCompare(right)
  })
})

const audienceOptions = computed(() => {
  const unique = new Set(documents.value.map(doc => doc.audience).filter(Boolean).filter(value => value !== 'all'))
  return Array.from(unique).sort((left, right) => {
    const leftIndex = audienceOrder.indexOf(left)
    const rightIndex = audienceOrder.indexOf(right)
    if (leftIndex !== -1 || rightIndex !== -1) {
      return (leftIndex === -1 ? 999 : leftIndex) - (rightIndex === -1 ? 999 : rightIndex)
    }
    return left.localeCompare(right)
  })
})

const sortedDocuments = computed(() => {
  return [...documents.value].sort((left, right) => {
    const leftOrder = Number(left.sort_order ?? 100)
    const rightOrder = Number(right.sort_order ?? 100)
    if (leftOrder !== rightOrder) return leftOrder - rightOrder
    return left.title.localeCompare(right.title)
  })
})

const filteredDocuments = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()

  return sortedDocuments.value.filter(doc => {
    const audienceMatch = selectedAudience.value === 'all' || doc.audience === selectedAudience.value || doc.audience === 'all'
    if (!audienceMatch) return false

    const categoryMatch = selectedCategory.value === 'all' || doc.category === selectedCategory.value
    if (!categoryMatch) return false

    if (!query) return true
    const haystack = [
      doc.title,
      doc.description,
      doc.category,
      doc.audience,
      doc.path,
    ].filter(Boolean).join(' ').toLowerCase()
    return haystack.includes(query)
  })
})

const groupedFilteredDocuments = computed(() => {
  return categoryOptions.value
    .map(category => ({
      category,
      documents: filteredDocuments.value.filter(doc => doc.category === category)
    }))
    .filter(group => group.documents.length)
})

const pathToDocId = computed(() => {
  const entries = new Map()
  documents.value.forEach((doc) => {
    if (!doc.path || !doc.id) return
    const normalized = normalizeDocPath(doc.path)
    entries.set(normalized, doc.id)
    entries.set(`docs/${normalized}`, doc.id)
  })
  return entries
})

const renderedHtml = computed(() => {
  if (!activeDocument.value?.content) return ''

  const rendered = marked.parse(activeDocument.value.content)
  // Ensure mermaid classes are preserved
  const sanitized = DOMPurify.sanitize(rendered, {
    ADD_TAGS: ['div', 'video', 'source', 'track'],
    ADD_ATTR: ['class', 'controls', 'muted', 'playsinline', 'preload', 'poster', 'src', 'type', 'target', 'rel']
  })
  return decorateDocumentationLinks(sanitized)
})

// Re-render mermaid diagrams when content changes
watch(renderedHtml, async () => {
  const renderToken = ++mermaidRenderToken
  await nextTick()

  const container = document.querySelector('.doc-markdown')
  if (!container) {
    return
  }

  const codeBlocks = container.querySelectorAll('pre code.language-mermaid')
  if (!codeBlocks.length) {
    return
  }

  codeBlocks.forEach(block => {
    const pre = block.parentElement
    if (!pre) {
      return
    }
    const div = document.createElement('div')
    div.className = 'mermaid'
    div.textContent = block.textContent
    pre.replaceWith(div)
  })

  try {
    const mermaid = await ensureMermaid()
    if (renderToken !== mermaidRenderToken) {
      return
    }
    await mermaid.run({
      querySelector: '.doc-markdown .mermaid'
    })
  } catch (error) {
    console.error('Mermaid rendering failed:', error)
  }
})

async function ensureMermaid() {
  if (mermaidModule) {
    return mermaidModule
  }
  if (!mermaidModulePromise) {
    mermaidModulePromise = import('mermaid').then(({ default: mermaid }) => {
      mermaid.initialize({ startOnLoad: false })
      mermaidModule = mermaid
      return mermaid
    }).catch((error) => {
      mermaidModulePromise = null
      throw error
    })
  }
  return mermaidModulePromise
}

const formatCategory = (value) => {
  if (!value) return 'Unknown'
  return value.replace(/[_-]/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

const formatAudience = (value) => {
  if (value === 'all') return 'All Audiences'
  if (value === 'beginner') return 'Beginners'
  if (value === 'user') return 'Users'
  if (value === 'operator') return 'Operators'
  if (value === 'admin') return 'Operators'
  if (value === 'developer') return 'Developers'
  return formatCategory(value)
}

const getDocumentById = (docId) => documents.value.find(doc => doc.id === docId) || null

const normalizeDocPath = (value) => {
  const [rawPath] = String(value || '').split('#', 1)
  const segments = []
  rawPath
    .replace(/^\/+/, '')
    .split('/')
    .forEach((segment) => {
      if (!segment || segment === '.') return
      if (segment === '..') {
        segments.pop()
        return
      }
      segments.push(segment)
    })
  return segments.join('/')
}

const slugifyHeading = (value) => {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/<[^>]+>/g, '')
    .replace(/&[a-z0-9#]+;/gi, '')
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}

const resolveInternalDocHref = (href) => {
  const value = String(href || '').trim()
  if (!value || value.startsWith('#')) return null
  if (/^(https?:|mailto:|tel:)/i.test(value)) return null
  if (value.startsWith('/api/')) return null

  const [pathPart, hashPart = ''] = value.split('#')
  let candidatePath = pathPart
  if (candidatePath.startsWith('/docs/')) {
    const docId = candidatePath.replace(/^\/docs\//, '').replace(/^content\//, '')
    if (getDocumentById(docId)) {
      return { docId, hash: hashPart ? `#${hashPart}` : '' }
    }
  }
  if (candidatePath.startsWith('/')) return null

  const activePath = activeDocument.value?.path || ''
  const activeDirectory = activePath.includes('/') ? activePath.split('/').slice(0, -1).join('/') : ''
  const normalizedCandidate = normalizeDocPath(candidatePath)
  const relativeCandidate = normalizeDocPath(`${activeDirectory}/${candidatePath}`)
  const docId = pathToDocId.value.get(normalizedCandidate) || pathToDocId.value.get(relativeCandidate)
  return docId ? { docId, hash: hashPart ? `#${hashPart}` : '' } : null
}

const decorateDocumentationLinks = (html) => {
  if (typeof DOMParser === 'undefined') {
    return html
  }

  const parsed = new DOMParser().parseFromString(html, 'text/html')
  const headingIds = new Map()
  parsed.querySelectorAll('h1, h2, h3, h4, h5, h6').forEach((heading) => {
    if (heading.id) return
    const baseId = slugifyHeading(heading.textContent)
    if (!baseId) return
    const count = headingIds.get(baseId) || 0
    headingIds.set(baseId, count + 1)
    heading.id = count ? `${baseId}-${count + 1}` : baseId
  })

  parsed.querySelectorAll('a[href]').forEach((anchor) => {
    const href = anchor.getAttribute('href') || ''
    const internal = resolveInternalDocHref(href)
    if (internal) {
      anchor.setAttribute('data-doc-id', internal.docId)
      if (internal.hash) {
        anchor.setAttribute('data-doc-hash', internal.hash)
      }
      anchor.setAttribute('href', `/docs/${internal.docId}${internal.hash}`)
      return
    }

    if (/^https?:/i.test(href)) {
      anchor.setAttribute('target', '_blank')
      anchor.setAttribute('rel', 'noopener noreferrer')
    }
  })
  return parsed.body.innerHTML
}

const scrollToHash = async (hash = '') => {
  const effectiveHash = hash || (typeof window !== 'undefined' ? window.location.hash : '')
  if (!effectiveHash) return
  let id = effectiveHash.replace(/^#/, '')
  try {
    id = decodeURIComponent(id)
  } catch {
    return
  }
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await nextTick()
    if (typeof requestAnimationFrame === 'function') {
      await new Promise(resolve => requestAnimationFrame(resolve))
    }
    const target = document.getElementById(id)
    if (target) {
      target.scrollIntoView({ block: 'start' })
      return
    }
  }
}

const handleMarkdownClick = async (event) => {
  const link = event.target?.closest?.('a[data-doc-id]')
  if (!link) return
  const docId = link.getAttribute('data-doc-id')
  if (!docId) return
  event.preventDefault()
  await router.push({
    name: 'DocumentationDoc',
    params: { docId },
    hash: link.getAttribute('data-doc-hash') || '',
  })
  await loadDocumentById(docId)
  await scrollToHash(link.getAttribute('data-doc-hash') || '')
}

const loadDocumentById = async (docId) => {
  if (!docId) {
    activeDocument.value = null
    return
  }

  const cached = documentCache.value[docId]
  if (cached) {
    activeDocument.value = cached
    return
  }

  loadingDocument.value = true
  loadError.value = ''

  try {
    const response = await docsService.getDocument(docId)
    const docPayload = response?.data?.document

    if (!docPayload) {
      throw new Error('Document payload missing')
    }

    documentCache.value = {
      ...documentCache.value,
      [docId]: docPayload
    }

    activeDocument.value = docPayload
  } catch (error) {
    console.error('Failed to load document content:', error)
    loadError.value = error?.error?.message || error?.message || 'Failed to load documentation content.'
  } finally {
    loadingDocument.value = false
  }
}

const openDocument = async (doc, useReplace = false) => {
  if (!doc?.id) return

  const routeMethod = useReplace ? 'replace' : 'push'
  const currentId = route.params.docId

  if (currentId !== doc.id) {
    await router[routeMethod]({ name: 'DocumentationDoc', params: { docId: doc.id } })
  }

  await loadDocumentById(doc.id)
  if (!loadingIndex.value) {
    await scrollToHash(route.hash)
  }
}

const initializeDocuments = async () => {
  loadingIndex.value = true
  loadError.value = ''

  try {
    const response = await docsService.listDocuments()
    const docs = response?.data?.documents || []

    documents.value = docs

    if (!docs.length) {
      loadError.value = 'No documentation entries are currently available.'
      return
    }

    const requestedId = route.params.docId

    // Prefer the beginner start-here guide as the Documentation Center landing page.
    const landingDoc = docs.find(d =>
      d.id === 'user-guide' ||
      (d.category === 'start-here' && ['beginner', 'user'].includes(d.audience)) ||
      (d.title && d.title.toLowerCase().includes('end-to-end user guide'))
    )

    const defaultDoc = getDocumentById(requestedId) || landingDoc || docs[0]
    await openDocument(defaultDoc, !requestedId)
  } catch (error) {
    console.error('Failed to load documentation index:', error)
    loadError.value = error?.error?.message || error?.message || 'Failed to load documentation index.'
  } finally {
    loadingIndex.value = false
    await scrollToHash(route.hash)
  }
}

watch(
  () => route.params.docId,
  async (docId) => {
    if (!documents.value.length) return

    const candidate = getDocumentById(docId)
    if (candidate) {
      await loadDocumentById(candidate.id)
      await scrollToHash(route.hash)
    }
  }
)

watch(
  () => route.hash,
  async (hash) => {
    await scrollToHash(hash)
  }
)

onMounted(async () => {
  await initializeDocuments()
})
</script>

<style scoped>
.doc-markdown {
  color: #1e293b;
  line-height: 1.75;
  font-size: 0.97rem;
}

.doc-markdown :deep(h1),
.doc-markdown :deep(h2),
.doc-markdown :deep(h3),
.doc-markdown :deep(h4) {
  color: #0f172a;
  font-weight: 700;
  line-height: 1.3;
  margin-top: 1.6rem;
  margin-bottom: 0.65rem;
  scroll-margin-top: 1rem;
}

.doc-markdown :deep(h1) {
  font-size: 1.8rem;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 0.35rem;
}

.doc-markdown :deep(h2) {
  font-size: 1.45rem;
}

.doc-markdown :deep(h3) {
  font-size: 1.2rem;
}

.doc-markdown :deep(p),
.doc-markdown :deep(li) {
  color: #334155;
}

.doc-markdown :deep(ul),
.doc-markdown :deep(ol) {
  margin: 0.5rem 0 1rem 1.2rem;
}

.doc-markdown :deep(ul) {
  list-style-type: disc;
}

.doc-markdown :deep(ol) {
  list-style-type: decimal;
}

.doc-markdown :deep(code) {
  background: #e2e8f0;
  color: #0f172a;
  padding: 0.1rem 0.35rem;
  border-radius: 0.3rem;
  font-size: 0.87em;
}

.doc-markdown :deep(pre) {
  background: #0f172a;
  color: #e2e8f0;
  padding: 1rem;
  border-radius: 0.75rem;
  overflow-x: auto;
  margin: 1rem 0;
}

.doc-markdown :deep(pre code) {
  background: transparent;
  color: inherit;
  padding: 0;
}

.doc-markdown :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 1rem 0;
  font-size: 0.92rem;
}

.doc-markdown :deep(th),
.doc-markdown :deep(td) {
  border: 1px solid #cbd5e1;
  padding: 0.6rem;
  text-align: left;
}

.doc-markdown :deep(th) {
  background: #f1f5f9;
  color: #0f172a;
}

.doc-markdown :deep(blockquote) {
  border-left: 4px solid #38bdf8;
  background: #f0f9ff;
  color: #0f172a;
  padding: 0.7rem 1rem;
  margin: 1rem 0;
}

.doc-markdown :deep(a) {
  color: #0369a1;
  text-decoration: underline;
}

.doc-markdown :deep(hr) {
  border: none;
  border-top: 1px solid #e2e8f0;
  margin: 1.5rem 0;
}

.doc-markdown :deep(video) {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 0.75rem;
  background: #0f172a;
  margin: 1rem 0;
}
</style>
