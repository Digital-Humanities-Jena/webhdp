<template>
  <aside class="space-y-4 xl:sticky xl:top-28 xl:max-h-[calc(100vh-8rem)] xl:overflow-y-auto">
    <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div class="space-y-3">
        <div>
          <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Search Components</label>
          <input
            aria-label="Search components" v-model.trim="catalogSearchModel"
            type="text"
            class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
            placeholder="Search by name, tag, or keyword"
          />
        </div>
        <div>
          <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Category</label>
          <select aria-label="Component category" v-model="catalogCategoryModel" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" data-testid="catalog-category-filter">
            <option value="">All categories</option>
            <option v-for="category in componentCategories" :key="category" :value="category">
              {{ category }}
            </option>
          </select>
        </div>
        <div>
          <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Tag</label>
          <select aria-label="Component tag" v-model="catalogTagModel" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" data-testid="catalog-tag-filter">
            <option value="">All tags</option>
            <option v-for="tag in componentTags" :key="tag" :value="tag">
              {{ tag }}
            </option>
          </select>
        </div>
        <div>
          <label class="mb-2 block text-xs font-semibold uppercase tracking-wide text-slate-500">Execution Profile</label>
          <select aria-label="Runtime profile" v-model="catalogProfileModel" class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm" data-testid="catalog-profile-filter">
            <option value="">All profiles</option>
            <option v-for="profile in componentProfiles" :key="profile" :value="profile">
              {{ profile }}
            </option>
          </select>
        </div>
        <button
          v-if="catalogSearch || catalogCategory || catalogTag || catalogProfile"
          type="button"
          class="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          data-testid="catalog-clear-filters"
          @click="$emit('clear-catalog-filters')"
        >
          Clear Filters
        </button>
      </div>
    </section>

    <section class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div class="flex items-center justify-between">
        <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-700">Component Catalog</h2>
        <span class="text-xs text-slate-500">{{ filteredComponents.length }}</span>
      </div>
      <div class="mt-4 space-y-3">
        <article
          v-for="component in filteredComponents"
          :key="component.key"
          class="rounded-xl border border-slate-200 bg-slate-50 p-4"
        >
          <div class="flex items-start justify-between gap-3">
            <div>
              <h3 class="text-sm font-semibold text-slate-900">{{ component.constructor_schema?.title || component.name }}</h3>
              <p class="mt-1 text-xs text-slate-500">{{ component.constructor_schema?.metadata?.category || 'Uncategorized' }}</p>
              <p class="mt-1 text-xs text-slate-500">
                Profiles:
                {{ (component.constructor_schema?.profiles || []).map((profile) => profile.id).join(', ') || 'builtin_default' }}
              </p>
            </div>
            <button
              type="button"
              class="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800"
              :aria-label="`Add ${component.name}`" :data-testid="`catalog-add-${component.key}`"
              @click="$emit('add-step-from-component', component)"
            >
              Add
            </button>
          </div>
          <p class="mt-3 text-sm text-slate-600">{{ component.description }}</p>
          <div class="mt-3 flex flex-wrap gap-2">
            <span
              v-for="tag in (component.constructor_schema?.metadata?.tags || []).slice(0, 4)"
              :key="`${component.key}-${tag}`"
              class="rounded-full bg-white px-2 py-1 text-[11px] font-medium text-slate-600"
            >
              {{ tag }}
            </span>
          </div>
        </article>
        <p v-if="filteredComponents.length === 0" class="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500">
          No components match the current filters.
        </p>
      </div>
    </section>

    <section v-if="isAdmin" class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-700">Admin Intake</h2>
      <p class="mt-2 text-sm text-slate-500">
        Validate or import executable HDP components. Pipeline authors can use registered components but cannot import new ones.
      </p>
      <div class="mt-4 space-y-3">
        <input
          aria-label="Component manifest path" v-model.trim="componentPathModel"
          type="text"
          class="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm"
          placeholder="/absolute/path/to/component"
        />
        <div class="flex gap-2">
          <button
            type="button"
            class="flex-1 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            :disabled="validatingComponent"
            @click="$emit('validate-component-path')"
          >
            {{ validatingComponent ? 'Validating...' : 'Validate' }}
          </button>
          <button
            type="button"
            class="flex-1 rounded-xl bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            :disabled="importingComponent"
            @click="$emit('import-component-path')"
          >
            {{ importingComponent ? 'Importing...' : 'Import' }}
          </button>
        </div>
        <div v-if="componentValidationResult" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600">
          <div class="font-semibold text-slate-800">
            {{ componentValidationResult.constructor_schema?.title || componentValidationResult.manifest?.metadata?.label }}
          </div>
          <div class="mt-1">Playground: {{ componentValidationResult.playground_schema?.title || 'n/a' }}</div>
          <div class="mt-1">Constructor: {{ componentValidationResult.constructor_schema?.title || 'n/a' }}</div>
        </div>
      </div>
    </section>
  </aside>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  catalogSearch: {
    type: String,
    required: true,
  },
  catalogCategory: {
    type: String,
    required: true,
  },
  catalogTag: {
    type: String,
    required: true,
  },
  catalogProfile: {
    type: String,
    required: true,
  },
  componentCategories: {
    type: Array,
    required: true,
  },
  componentTags: {
    type: Array,
    required: true,
  },
  componentProfiles: {
    type: Array,
    required: true,
  },
  filteredComponents: {
    type: Array,
    required: true,
  },
  isAdmin: {
    type: Boolean,
    default: false,
  },
  componentPath: {
    type: String,
    required: true,
  },
  validatingComponent: {
    type: Boolean,
    default: false,
  },
  importingComponent: {
    type: Boolean,
    default: false,
  },
  componentValidationResult: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits([
  'update:catalog-search',
  'update:catalog-category',
  'update:catalog-tag',
  'update:catalog-profile',
  'update:component-path',
  'clear-catalog-filters',
  'add-step-from-component',
  'validate-component-path',
  'import-component-path',
])

const catalogSearchModel = computed({
  get: () => props.catalogSearch,
  set: (value) => emit('update:catalog-search', value),
})

const catalogCategoryModel = computed({
  get: () => props.catalogCategory,
  set: (value) => emit('update:catalog-category', value),
})

const catalogTagModel = computed({
  get: () => props.catalogTag,
  set: (value) => emit('update:catalog-tag', value),
})

const catalogProfileModel = computed({
  get: () => props.catalogProfile,
  set: (value) => emit('update:catalog-profile', value),
})

const componentPathModel = computed({
  get: () => props.componentPath,
  set: (value) => emit('update:component-path', value),
})
</script>
