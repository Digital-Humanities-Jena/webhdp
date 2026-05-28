import { expect, test } from '@playwright/test'

import { apiV1, fulfillJson, loginThroughUi, mockLogin, mockSetupStatus } from './support/api'

test.describe('Workflow browser happy paths', () => {
  test('supports the manual upload path into file review', async ({ page }) => {
    await mockSetupStatus(page, true)
    await mockLogin(page)
    await page.route(apiV1('/sessions/file'), async (route) => {
      await fulfillJson(route, {
        data: {
          session_id: 41,
          foundFiles: [
            {
              file_id: 1,
              name: 'manual.glb',
              filename: 'manual.glb',
              relative_path: 'manual.glb',
              status: 'uploaded',
              children: [],
            },
          ],
        },
      })
    })
    await page.route(apiV1('/sessions/41/workflow-state'), async (route) => {
      await fulfillJson(route, { data: { ok: true } })
    })

    await loginThroughUi(page)
    await page.locator('#file-upload').setInputFiles({
      name: 'manual.glb',
      mimeType: 'model/gltf-binary',
      buffer: Buffer.from('glb'),
    })
    await page.getByTestId('upload-primary-action').click()

    await expect(page).toHaveURL(/\/workflow\/files$/)
    await expect(page.getByRole('heading', { name: 'Review Files' })).toBeVisible()
  })

  test('keeps the user on upload and surfaces backend errors when manual upload fails', async ({ page }) => {
    await mockSetupStatus(page, true)
    await mockLogin(page)
    await page.route(apiV1('/sessions/file'), async (route) => {
      await fulfillJson(route, {
        error: {
          message: 'Upload failed for test',
        },
      }, 500)
    })

    await loginThroughUi(page)
    await page.locator('#file-upload').setInputFiles({
      name: 'broken.glb',
      mimeType: 'model/gltf-binary',
      buffer: Buffer.from('broken'),
    })
    await page.getByTestId('upload-primary-action').click()

    await expect(page).toHaveURL(/\/workflow\/upload$/)
    await expect(page.getByTestId('upload-error')).toHaveText(/Upload failed for test/)
  })

  test('supports the MSF batch upload path into guided MSF analysis', async ({ page }) => {
    await mockSetupStatus(page, true)
    await mockLogin(page)
    await page.route(apiV1('/admin/storage-status'), async (route) => {
      await fulfillJson(route, {
        data: {
          active_storage: 'dropbox',
          active_message: 'Cloud storage ready',
          config: {
            storage_mode: 'cloud_backup',
          },
        },
      })
    })
    await page.route(apiV1('/sessions/directory'), async (route) => {
      const requestUrl = new URL(route.request().url())
      if (requestUrl.searchParams.get('validate_only') === 'true') {
        await fulfillJson(route, {
          data: {
            msf_validation: {
              is_valid: true,
              matched_count: 1,
              matched_files: ['model-a.glb'],
            },
            msf_mapping: {},
            file_metadata_map: {},
            msf_profile: {
              parse_options: {},
            },
          },
        })
        return
      }

      await fulfillJson(route, {
        data: {
          task_id: null,
          session_id: 42,
          submit_token: 'submit-token-42',
        },
      })
    })
    await page.route(apiV1('/sessions/42/progress'), async (route) => {
      await fulfillJson(route, {
        data: {
          upload_progress: {
            percent: 100,
            failed_count: 0,
            current_stage: 'completed',
            status_message: 'Processing complete',
          },
        },
      })
    })
    await page.route(apiV1('/sessions/42/record-resolution/analyze'), async (route) => {
      await fulfillJson(route, {
        data: {
          summary: {
            affected_count: 0,
            can_continue: true,
            unresolved_count: 0,
          },
          candidates: [],
        },
      })
    })
    await page.route(apiV1('/msf/workflow/session/42/analyze'), async (route) => {
      await fulfillJson(route, {
        data: {
          analysis: {
            msf_path: '/tmp/source.xlsx',
            summary: {
              rows_total: 1,
              error_count: 0,
              warning_count: 0,
            },
            validator: {
              checks: {
                reference_availability: {
                  matched_count: 1,
                  missing_count: 0,
                },
              },
            },
            issues: [],
            recommended_fixes: [],
            preview: {
              columns: ['title'],
              preview_rows: [{ __row_number: 1, title: 'Model A' }],
            },
            highlight_cells: [],
            lod_samples: {
              edm: { valid: true, minimum_viable_applied: false, xml: '<edm />' },
              iiif: { valid: true, minimum_viable_applied: false, json: '{"label":"ok"}' },
              mets: { valid: true, minimum_viable_applied: false, xml: '<mets />' },
            },
            workflow_state: {
              requires_scan_start: false,
              active_msf_path: '/tmp/source.xlsx',
              original_msf_path: '/tmp/source.xlsx',
            },
            minimum_viable_options: [],
          },
        },
      })
    })
    await page.route(apiV1('/sessions/42/workflow-state'), async (route) => {
      await fulfillJson(route, { data: { ok: true } })
    })

    await loginThroughUi(page)
    await page.getByTestId('upload-path-batch').click()
    await expect(page.getByText('Cloud storage ready')).toBeVisible()
    await page.getByTestId('upload-zip-input').setInputFiles({
      name: 'models.zip',
      mimeType: 'application/zip',
      buffer: Buffer.from('zip-content'),
    })
    await page.getByTestId('upload-msf-input').setInputFiles({
      name: 'models.xlsx',
      mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      buffer: Buffer.from('xlsx-content'),
    })
    await page.getByTestId('upload-validate-msf').click()
    await expect(page.getByText('files matched')).toBeVisible()
    await page.getByTestId('upload-primary-action').click()

    await expect(page).toHaveURL(/\/workflow\/msf-analysis$/)
    await expect(page.getByRole('heading', { name: 'MSF Analysis' })).toBeVisible()
    await expect(page.getByText('Session MSF Report')).toBeVisible()
  })
})
