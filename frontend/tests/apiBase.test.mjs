import { expect, test } from 'vitest'

import { buildApiBaseUrl, normalizeApiBaseUrl } from '../src/services/apiBase.js'

test('normalizeApiBaseUrl trims whitespace and trailing slashes', () => {
  expect(normalizeApiBaseUrl(' http://localhost:5000/api/v1/ ')).toBe('http://localhost:5000/api/v1')
})

test('buildApiBaseUrl upgrades a v1 URL to v2', () => {
  expect(buildApiBaseUrl('http://localhost:5000/api/v1', 'v2')).toBe('http://localhost:5000/api/v2')
})

test('buildApiBaseUrl appends a version to an origin-only URL', () => {
  expect(buildApiBaseUrl('http://localhost:5000', 'v1')).toBe('http://localhost:5000/api/v1')
})

test('buildApiBaseUrl appends a version to an api root URL', () => {
  expect(buildApiBaseUrl('/api', 'v2')).toBe('/api/v2')
})

test('buildApiBaseUrl preserves relative versioned URLs', () => {
  expect(buildApiBaseUrl('/api/v1', 'v2')).toBe('/api/v2')
})

test('buildApiBaseUrl rejects invalid versions', () => {
  expect(() => buildApiBaseUrl('http://localhost:5000', 'latest')).toThrow(/Unsupported API version/)
})
