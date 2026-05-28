import { HttpResponse } from 'msw'

const TEST_ORIGIN = 'http://localhost:5000'

export function apiV1Url(path) {
  return new URL(`/api/v1${path}`, TEST_ORIGIN).toString()
}

export function apiV2Url(path) {
  return new URL(`/api/v2${path}`, TEST_ORIGIN).toString()
}

export function jsonResponse(body, options = {}) {
  return HttpResponse.json(body, options)
}

export async function readJsonBody(request) {
  return request.json()
}
