import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue' // MODIFIED: 'watch' has been added

// NEW: Function to get initial state from sessionStorage
const getInitialState = () => {
  const stored = sessionStorage.getItem('workflowState')
  if (stored) {
    try {
      return JSON.parse(stored)
    } catch (e) {
      console.error('Failed to parse workflow state, resetting.', e)
    }
  }
  // Default clean state
  return {
    currentStep: 1,
    sessionId: null,
    uploadedFiles: [],
    selectedFiles: [],
    submissionMetadata: {},
    selectedPipeline: null,
    // MSF-related state
    msfPath: null,
    msfValidation: null,
    msfMapping: {},
    fileMetadataMap: {},
    msfProfile: {},
    msfParseOptions: {},
    isBatchMode: false,
    lodMinimumViablePrefs: { edm: true, iiif: true, mets: true }
  }
}

export const useWorkflowStore = defineStore('workflow', () => {
  // Initialize state from sessionStorage
  const initialState = getInitialState()

  const currentStep = ref(initialState.currentStep)
  const sessionId = ref(initialState.sessionId)
  const uploadedFiles = ref(initialState.uploadedFiles)
  const selectedFiles = ref(initialState.selectedFiles)
  const submissionMetadata = ref(initialState.submissionMetadata)
  const selectedPipeline = ref(initialState.selectedPipeline)

  // MSF-related state
  const msfPath = ref(initialState.msfPath)
  const msfValidation = ref(initialState.msfValidation)
  const msfMapping = ref(initialState.msfMapping || {})
  const fileMetadataMap = ref(initialState.fileMetadataMap || {})
  const msfProfile = ref(initialState.msfProfile || {})
  const msfParseOptions = ref(initialState.msfParseOptions || {})
  const isBatchMode = ref(initialState.isBatchMode)
  const lodMinimumViablePrefs = ref(initialState.lodMinimumViablePrefs || { edm: true, iiif: true, mets: true })

  const totalSteps = ref(7)

  // DEPRECATED
  const fileMetadata = ref({})
  const userMetadata = ref({})

  const canGoNext = computed(() => currentStep.value < totalSteps.value)
  const canGoBack = computed(() => currentStep.value > 1)

  function nextStep() {
    if (canGoNext.value) currentStep.value++
  }

  function prevStep() {
    if (canGoBack.value) currentStep.value--
  }

  function goToStep(step) {
    if (step >= 1 && step <= totalSteps.value) {
      currentStep.value = step
    }
  }

  function setSessionId(id) {
    sessionId.value = id
  }

  function setUploadedFiles(files) {
    uploadedFiles.value = files
  }

  function setSelectedFiles(files) {
    selectedFiles.value = files || []
  }

  function addFileMetadata(fileId, metadata) {
    fileMetadata.value[fileId] = metadata
  }

  function setUserMetadata(metadata) {
    userMetadata.value = metadata
  }

  function setSubmissionMetadata(metadata) {
    submissionMetadata.value = metadata
  }

  function setPipeline(pipeline) {
    selectedPipeline.value = pipeline
  }

  function resetWorkflow() {
    currentStep.value = 1
    sessionId.value = null
    uploadedFiles.value = []
    selectedFiles.value = []
    fileMetadata.value = {}
    userMetadata.value = {}
    submissionMetadata.value = {}
    selectedPipeline.value = null
    msfPath.value = null
    msfValidation.value = null
    msfMapping.value = {}
    fileMetadataMap.value = {}
    msfProfile.value = {}
    msfParseOptions.value = {}
    isBatchMode.value = false
    lodMinimumViablePrefs.value = { edm: true, iiif: true, mets: true }
    sessionStorage.removeItem('workflowState')
  }

  function setMsfData(path, validation, mapping = {}, metadataMap = {}, profile = {}, parseOptions = null) {
    msfPath.value = path
    msfValidation.value = validation
    msfMapping.value = mapping || {}
    fileMetadataMap.value = metadataMap || {}
    msfProfile.value = profile || {}
    msfParseOptions.value = parseOptions || profile?.parse_options || {}
    isBatchMode.value = true
  }

  function setBatchMode(val) {
    isBatchMode.value = val
  }

  function setMsfPath(path) {
    msfPath.value = path || null
  }

  function setFileMetadataMap(metadataMap) {
    fileMetadataMap.value = metadataMap
  }

  function setMsfMapping(mapping) {
    msfMapping.value = mapping || {}
  }

  function setMsfProfile(profile) {
    msfProfile.value = profile || {}
  }

  function setMsfParseOptions(options) {
    msfParseOptions.value = options || {}
  }

  function setLodMinimumViablePrefs(prefs) {
    lodMinimumViablePrefs.value = {
      edm: prefs?.edm !== false,
      iiif: prefs?.iiif !== false,
      mets: prefs?.mets !== false
    }
  }

  const stateToPersist = computed(() => ({
    currentStep: currentStep.value,
    sessionId: sessionId.value,
    uploadedFiles: uploadedFiles.value,
    selectedFiles: selectedFiles.value,
    submissionMetadata: submissionMetadata.value,
    selectedPipeline: selectedPipeline.value,
    msfPath: msfPath.value,
    msfValidation: msfValidation.value,
    msfMapping: msfMapping.value,
    fileMetadataMap: fileMetadataMap.value,
    msfProfile: msfProfile.value,
    msfParseOptions: msfParseOptions.value,
    isBatchMode: isBatchMode.value,
    lodMinimumViablePrefs: lodMinimumViablePrefs.value
  }))

  watch(stateToPersist, (newState) => {
    sessionStorage.setItem('workflowState', JSON.stringify(newState))
  }, { deep: true })

  return {
    currentStep,
    sessionId,
    uploadedFiles,
    selectedFiles,
    fileMetadata,
    userMetadata,
    submissionMetadata,
    selectedPipeline,
    msfPath,
    msfValidation,
    msfMapping,
    fileMetadataMap,
    msfProfile,
    msfParseOptions,
    isBatchMode,
    lodMinimumViablePrefs,
    totalSteps,
    canGoNext,
    canGoBack,
    nextStep,
    prevStep,
    goToStep,
    setSessionId,
    setUploadedFiles,
    setSelectedFiles,
    addFileMetadata,
    setUserMetadata,
    setSubmissionMetadata,
    setPipeline,
    setSelectedPipeline: setPipeline,
    setMsfData,
    setFileMetadataMap,
    setMsfMapping,
    setMsfProfile,
    setMsfParseOptions,
    setMsfPath,
    setBatchMode,
    setLodMinimumViablePrefs,
    resetWorkflow
  }
})
