// frontend/src/router/index.js
import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useSystemStore } from '@/stores/system'
import MainLayout from '@/components/layout/MainLayout.vue'

const routes = [
  {
    path: '/',
    name: 'Landing',
    component: () => import('@/views/public/LandingView.vue'),
    meta: { publicRoute: true, redirectAuthenticated: '/workflow/upload' }
  },
  {
    path: '/setup',
    name: 'Setup',
    component: () => import('@/views/setup/SetupView.vue')
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/auth/LoginView.vue')
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/auth/RegisterView.vue')
  },
  {
    path: '/verify-email/:token',
    name: 'VerifyEmail',
    component: () => import('@/views/auth/VerifyEmailView.vue')
  },
  {
    path: '/docs',
    name: 'DocumentationHub',
    component: () => import('@/views/docs/DocumentationHubView.vue')
  },
  {
    path: '/docs/:docId',
    name: 'DocumentationDoc',
    component: () => import('@/views/docs/DocumentationHubView.vue')
  },
  {
    path: '/credits',
    name: 'Credits',
    component: () => import('@/views/public/CreditsView.vue'),
    meta: { publicRoute: true }
  },
  {
    path: '/model-publication/samples',
    name: 'ModelPublicationSamples',
    component: () => import('@/views/public/ModelPublicationSamplesView.vue'),
    meta: { publicRoute: true }
  },
  {
    path: '/impressum',
    name: 'Impressum',
    component: () => import('@/views/legal/ImpressumView.vue'),
    meta: { publicRoute: true }
  },
  {
    path: '/privacy',
    name: 'PrivacyPolicy',
    component: () => import('@/views/legal/PrivacyPolicyView.vue'),
    meta: { publicRoute: true }
  },
  {
    path: '/cookies',
    name: 'CookiePolicy',
    component: () => import('@/views/legal/CookiePolicyView.vue'),
    meta: { publicRoute: true }
  },
  {
    path: '/p/records/:environment/:zenodoRecordId',
    name: 'PublicRecord',
    component: () => import('@/views/public/PublicRecordView.vue'),
    meta: { publicRoute: true }
  },
  {
    path: '/embed/records/:environment/:zenodoRecordId',
    name: 'EmbedRecord',
    component: () => import('@/views/public/EmbedRecordView.vue'),
    meta: { publicRoute: true }
  },

  {
    path: '/',
    component: MainLayout,
    meta: { requiresAuth: true },
    children: [
      {
        path: 'model-publication',
        name: 'ModelPublication',
        component: () => import('@/views/workflow/ModelPublicationView.vue'),
      },
      {
        path: 'link/jobs',
        name: 'LinkedProcessing',
        component: () => import('@/views/link/LinkedProcessingView.vue'),
      },
      {
        path: 'link/jobs/:runId',
        name: 'LinkedProcessingDetail',
        component: () => import('@/views/link/LinkedProcessingView.vue'),
      },
      {
        path: 'link/authorize',
        name: 'LinkAuthorize',
        component: () => import('@/views/link/LinkAuthorizeView.vue'),
      },
      {
        path: 'admin/webhdp-link',
        name: 'WebHdpLinkAdmin',
        component: () => import('@/views/admin/WebHdpLinkView.vue'),
        meta: { requiresAdmin: true },
      },
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/DashboardView.vue'),
      },
      {
        path: 'onboarding',
        name: 'Onboarding',
        component: () => import('@/views/onboarding/OnboardingView.vue'),
      },
      {
        path: 'hpc-resources',
        name: 'HpcResources',
        component: () => import('@/views/hpc/HpcResourceRequestView.vue'),
      },
      {
        path: 'notifications',
        name: 'Notifications',
        component: () => import('@/views/notifications/NotificationsView.vue'),
      },
      {
        path: 'developer',
        name: 'DeveloperMode',
        component: () => import('@/views/developer/DeveloperModeView.vue'),
        meta: { requiresDeveloper: true },
      },
      // Admin Dashboard (Operational)
      {
        path: 'admin/dashboard',
        name: 'AdminDashboard',
        component: () => import('@/views/admin/AdminDashboardView.vue'),
        meta: { requiresModerator: true }
      },
      {
        path: 'admin/setup',
        name: 'AdminSetupGuidance',
        component: () => import('@/views/admin/OperationalReadinessView.vue'),
        meta: { requiresAdmin: true }
      },
      {
        path: 'admin/review/:id',
        name: 'AdminReview',
        component: () => import('@/views/admin/ReviewSubmissionView.vue'),
        meta: { requiresModerator: true }
      },
      {
        path: 'admin/hpc-access',
        name: 'AdminHpcAccess',
        component: () => import('@/views/admin/AdminHpcAccessView.vue'),
        meta: { requiresAdmin: true }
      },
      {
        path: 'admin/session-monitoring',
        name: 'AdminSessionMonitoring',
        component: () => import('@/views/admin/AdminSessionMonitoringView.vue'),
        meta: { requiresAdmin: true }
      },

      // Settings Section (Configuration)
      {
        path: 'settings',
        component: () => import('@/views/settings/SettingsLayout.vue'),
        meta: { requiresAdmin: true },
        redirect: '/settings/pipelines',
        children: [
          {
            path: 'pipelines',
            name: 'PipelineConfig',
            component: () => import('@/views/admin/PipelineConfigView.vue'),
          },
          {
            path: 'edm',
            name: 'EdmConfig',
            component: () => import('@/views/admin/EdmConfigView.vue'),
          },
          {
            path: 'edm-templates',
            name: 'EdmTemplates',
            component: () => import('@/views/admin/EdmTemplatesView.vue'),
          },
          {
            path: 'cloud-testing',
            name: 'CloudTesting',
            component: () => import('@/views/admin/CloudTestingView.vue'),
          },
          {
            path: 'storage',
            name: 'StorageConfig',
            component: () => import('@/views/admin/StorageConfigView.vue'),
          },
          {
            path: 'mfa',
            name: 'MfaConfig',
            component: () => import('@/views/admin/MfaConfigView.vue'),
          },
          {
            path: 'modalities',
            name: 'ModalityConfig',
            component: () => import('@/views/admin/ModalitySettingsView.vue'),
          },
          {
            path: 'observability/credentials',
            name: 'ObservabilityCredentials',
            component: () => import('@/views/admin/ObservabilityCredentialsView.vue'),
          },
          {
            path: 'observability/api-activity',
            name: 'ObservabilityApiActivity',
            component: () => import('@/views/admin/ObservabilityApiActivityView.vue'),
          },
          {
            path: 'observability/notifications',
            name: 'ObservabilityNotifications',
            component: () => import('@/views/admin/ObservabilityNotificationsView.vue'),
          }
        ]
      },

      {
        path: 'workflow/upload',
        name: 'Upload',
        component: () => import('@/views/workflow/UploadView.vue'),
      },
      {
        path: 'workflow/msf-analysis',
        name: 'MsfAnalysis',
        component: () => import('@/views/workflow/MsfAnalysisView.vue'),
      },
      {
        path: 'workflow/files',
        name: 'Files',
        component: () => import('@/views/workflow/FilesView.vue'),
      },
      {
        path: 'workflow/file-metadata',
        redirect: '/workflow/metadata'
      },
      {
        path: 'workflow/user-metadata',
        redirect: '/workflow/metadata'
      },
      {
        path: 'workflow/metadata',
        name: 'SubmissionMetadata',
        component: () => import('@/views/workflow/SubmissionMetadataView.vue')
      },
      {
        path: 'workflow/edm-selection',
        name: 'EdmSelection',
        component: () => import('@/views/workflow/EdmSelectionView.vue')
      },
      {
        path: 'workflow/submit',
        name: 'Submit',
        component: () => import('@/views/workflow/SubmitView.vue'),
      },
      {
        path: 'workflow/pipeline',
        name: 'Pipeline',
        component: () => import('@/views/workflow/PipelineView.vue'),
      },
      {
        path: 'workflow/processing',
        name: 'Processing',
        component: () => import('@/views/workflow/ProcessingView.vue'),
      },
      {
        path: 'submissions',
        name: 'Submissions',
        component: () => import('@/views/dashboard/SubmissionsView.vue'),
      },
      {
        path: 'uploads',
        name: 'UploadOperations',
        component: () => import('@/views/dashboard/UploadOperationsView.vue'),
      },
      {
        path: 'uploads/:sessionId',
        name: 'UploadOperationDetail',
        component: () => import('@/views/dashboard/UploadOperationDetailView.vue'),
      },
      {
        path: 'submissions/:id',
        name: 'SubmissionDetail',
        component: () => import('@/views/dashboard/SubmissionDetailView.vue'),
      },
      {
        path: 'runs/:runId',
        name: 'PipelineRunDetail',
        component: () => import('@/views/dashboard/SubmissionDetailView.vue'),
      },
      {
        path: 'sessions/:sessionId/records',
        name: 'SessionRecords',
        component: () => import('@/views/dashboard/SessionRecordsView.vue'),
      },
      {
        path: 'sessions/:sessionId/records/:recordId',
        name: 'SessionRecordDetail',
        component: () => import('@/views/dashboard/RecordDetailView.vue'),
      },
      {
        path: 'sessions/:sessionId/provenance-report',
        name: 'SessionProvenanceReport',
        component: () => import('@/views/dashboard/SessionProvenanceReportView.vue'),
      },
      {
        path: 'records/explorer',
        name: 'CrossSessionRecordsExplorer',
        component: () => import('@/views/dashboard/CrossSessionRecordsExplorerView.vue'),
      },
      {
        path: 'datasets/:datasetKey?',
        name: 'DatasetIntegrityWorkspace',
        component: () => import('@/views/dashboard/DatasetIntegrityWorkspaceView.vue'),
      },
      {
        path: 'profiles/users/:identifier',
        name: 'UserProfile',
        component: () => import('@/views/profiles/UserProfileView.vue'),
      },
      {
        path: 'profiles/institutions/:identifier',
        name: 'InstitutionProfile',
        component: () => import('@/views/profiles/InstitutionProfileView.vue'),
      },
      {
        path: 'issues',
        name: 'IssuesWorkspace',
        component: () => import('@/views/issues/IssuesWorkspaceView.vue'),
      },
      {
        path: 'issues/report',
        name: 'IssueReport',
        component: () => import('@/views/issues/IssueReportView.vue'),
      },
      {
        path: 'issues/:issueId',
        name: 'IssueDetail',
        component: () => import('@/views/issues/IssueDetailView.vue'),
      },
      {
        path: 'tools',
        name: 'ToolsOverview',
        component: () => import('@/views/tools/ToolsLayout.vue'),
        children: [
          {
            path: 'playground',
            name: 'Playground',
            component: () => import('@/views/tools/NativePlaygroundView.vue'),
          },
          {
            path: 'native-playground',
            redirect: '/tools/playground',
          },
          {
            path: 'pipeline-preflight',
            name: 'PipelinePreflight',
            component: () => import('@/views/tools/PipelinePreflightView.vue'),
          },
          {
            path: 'pipeline-constructor',
            name: 'PipelineConstructor',
            component: () => import('@/views/admin/PipelineConfigView.vue'),
            meta: { requiresPipelineAuthor: true },
          },
          {
            path: 'msf-validator-local',
            name: 'MsfValidatorLocal',
            component: () => import('@/views/tools/MsfValidatorLocalView.vue'),
          },
          {
            path: 'msf-reference-repair',
            name: 'MsfReferenceRepair',
            component: () => import('@/views/tools/MsfReferenceRepairView.vue'),
          },
          {
            path: 'metadata-normalizer',
            name: 'MetadataNormalizer',
            component: () => import('@/views/tools/MetadataNormalizerView.vue'),
          },
          {
            path: 'output-preview-qa',
            name: 'OutputPreviewQa',
            component: () => import('@/views/tools/OutputPreviewQaView.vue'),
          },
          {
            path: 'hpc-diagnostics',
            name: 'HpcDiagnostics',
            component: () => import('@/views/tools/HpcDiagnosticsView.vue'),
          },
          {
            path: 'hdp-components/install',
            name: 'HdpComponentInstaller',
            component: () => import('@/views/tools/HdpComponentInstallerView.vue'),
            meta: { requiresAdmin: true },
          },
          {
            path: 'session-cleanup',
            name: 'SessionCleanup',
            component: () => import('@/views/tools/SessionCleanupView.vue'),
          },
          {
            path: 'zenodo-batch-operations',
            name: 'ZenodoBatchOperations',
            component: () => import('@/views/tools/ZenodoBatchOperationsView.vue'),
            meta: { requiresModerator: true },
          },
          {
            path: 'zenodo-account-retrieval',
            name: 'ZenodoAccountRetrieval',
            component: () => import('@/views/tools/ZenodoAccountRetrievalView.vue'),
          },
          {
            path: 'zenodo-oai-harvest',
            name: 'ZenodoOaiHarvest',
            component: () => import('@/views/tools/ZenodoOaiHarvestView.vue'),
          },
          {
            path: 'community-moderation',
            name: 'CommunityModeration',
            component: () => import('@/views/tools/CommunityModerationPanelView.vue'),
            meta: { requiresModerator: true },
          },
          {
            path: 'community-migration',
            name: 'CommunityMigration',
            component: () => import('@/views/tools/CommunityMigrationView.vue'),
            meta: { requiresModerator: true },
          }
        ]
      },
      {
        path: 'account/connected-apps',
        name: 'ConnectedApplications',
        component: () => import('@/views/link/ConnectedApplicationsView.vue'),
      },
      {
        path: 'account/configuration',
        name: 'AccountConfiguration',
        component: () => import('@/views/account/AccountConfigurationView.vue'),
      },
      {
        path: 'account/institutions',
        name: 'InstitutionWorkspace',
        component: () => import('@/views/account/InstitutionWorkspaceView.vue'),
      }
    ]
  },

  // Fallback redirect
  {
    path: '/:pathMatch(.*)*',
    redirect: '/login'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.hash) return { el: to.hash, top: 16 }
    if (to.path === from.path) return false
    return { top: 0, left: 0 }
  }
})

// Navigation guard
router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()
  const systemStore = useSystemStore()
  const isDocsRoute = to.path === '/docs' || to.path.startsWith('/docs/')
  const isPublicRoute = Boolean(to.meta.publicRoute)

  if (to.meta.redirectAuthenticated && authStore.isAuthenticated) {
    next(to.meta.redirectAuthenticated)
    return
  }

  // Check system status
  if (!isPublicRoute) {
    await systemStore.checkStatus()
  }

  if (!systemStore.isInitialized && to.path !== '/setup' && !isDocsRoute && !isPublicRoute) {
    const setupToken = String(to.query.setup_token || '').trim()
    next({
      path: '/setup',
      query: setupToken ? { setup_token: setupToken } : {},
    })
    return
  }

  if (systemStore.isInitialized && to.path === '/setup') {
    next('/')
    return
  }

  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    next(['LinkAuthorize', 'LinkedProcessing', 'LinkedProcessingDetail', 'ModelPublication'].includes(to.name) ? { path: '/login', query: { redirect: to.fullPath } } : '/login')
  } else if (to.meta.requiresAuth) {
    if (!authStore.user) {
      await authStore.fetchCurrentUser()
    }
    if (authStore.user?.force_password_change && to.name !== 'AccountConfiguration') {
      next('/account/configuration?passwordChangeRequired=1')
      return
    }
    if (authStore.user?.model_publication_only && !authStore.user?.force_password_change) {
      next(to.name === 'ModelPublication' ? undefined : '/model-publication')
      return
    }
    if (authStore.user?.onboarding_required && to.name !== 'Onboarding' && to.name !== 'AccountConfiguration' && to.name !== 'HpcResources' && to.name !== 'LinkAuthorize' && to.name !== 'ConnectedApplications' && !['LinkedProcessing', 'LinkedProcessingDetail'].includes(to.name)) {
      next('/onboarding')
      return
    }

    if (to.meta.requiresAdmin) {
      // This is for ADMIN-ONLY pages
      if (authStore.user?.role !== 'admin') {
        next('/dashboard')
      } else {
        next()
      }
    } else if (to.meta.requiresModerator) {
      // This is for MODERATOR or ADMIN pages
      if (!['moderator', 'admin'].includes(authStore.user?.role)) {
        next('/dashboard')
      } else {
        next()
      }
    } else if (to.meta.requiresPipelineAuthor) {
      if (authStore.user?.role !== 'admin' && !authStore.hasCapability('native_pipeline_author')) {
        next('/dashboard')
      } else {
        next()
      }
    } else if (to.meta.requiresDeveloper) {
      if (
        !['admin', 'moderator'].includes(authStore.user?.role) &&
        !authStore.hasCapability('developer_access') &&
        !authStore.hasGroup('developer')
      ) {
        next('/dashboard')
      } else {
        next()
      }
    } else {
      next()
    }
  } else {
    next()
  }
})

export default router
