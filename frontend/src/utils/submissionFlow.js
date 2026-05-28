const pluralize = (count, singular, plural = `${singular}s`) => (
  count === 1 ? singular : plural
)

const normalizeMatchValue = (value) => String(value || '').trim().replaceAll('\\', '/').toLowerCase()

const buildSelectedFileMatchKeys = (file) => {
  const keys = new Set()
  const absolutePath = normalizeMatchValue(file?.absolute_path || file?.path)
  const relativePath = normalizeMatchValue(file?.relative_path)
  const filename = normalizeMatchValue(file?.filename || file?.name)

  if (absolutePath) {
    keys.add(`path:${absolutePath}`)
    keys.add(`name:${absolutePath.split('/').pop()}`)
  }
  if (relativePath) {
    keys.add(`path:${relativePath}`)
    keys.add(`name:${relativePath.split('/').pop()}`)
  }
  if (filename) {
    keys.add(`name:${filename}`)
  }
  return [...keys]
}

const buildCandidateMatchKeys = (candidate) => {
  const keys = new Set()
  const sourcePath = normalizeMatchValue(candidate?.candidate_source_file)
  const normalizedSourcePath = normalizeMatchValue(candidate?.normalized_source_file_path)
  const filename = normalizeMatchValue(candidate?.candidate_filename)

  for (const pathValue of [sourcePath, normalizedSourcePath]) {
    if (!pathValue) continue
    keys.add(`path:${pathValue}`)
    keys.add(`name:${pathValue.split('/').pop()}`)
  }
  if (filename) {
    keys.add(`name:${filename}`)
  }
  return [...keys]
}

const buildExecutionItemFromCandidate = (candidate) => {
  const action = String(candidate?.selected_action || candidate?.recommended_action || '').trim()
  const item = {
    decision_key: candidate?.decision_key,
    action,
    source_file_path: candidate?.candidate_source_file,
    source_file_name: candidate?.candidate_filename,
  }
  if (action === 'create_version') {
    const target = candidate?.selected_target || candidate?.recommended_target || {}
    item.target_session_id = target?.session_id ?? null
    item.target_local_record_id = target?.local_record_id ?? null
    item.target_concept_rec_id = target?.concept_rec_id || null
  }
  if (action === 'force_create_fresh') {
    item.forced_override_reason = candidate?.forced_override_reason || null
  }
  return item
}

export const resolveRecordResolutionSelections = ({ selectedFiles = [], candidates = [] } = {}) => {
  const indexedCandidates = new Map()
  const candidateList = Array.isArray(candidates) ? candidates.filter((candidate) => candidate && typeof candidate === 'object') : []

  candidateList.forEach((candidate) => {
    buildCandidateMatchKeys(candidate).forEach((key) => {
      if (!indexedCandidates.has(key)) {
        indexedCandidates.set(key, [])
      }
      indexedCandidates.get(key).push(candidate)
    })
  })

  const matchedCandidates = []
  const executionItems = []
  const unresolvedCandidates = []
  const unmatchedSelections = []
  const actionCounts = {
    create_fresh_record: 0,
    create_version: 0,
    skip: 0,
    force_create_fresh: 0,
  }
  const seenDecisionKeys = new Set()

  for (const selectedFile of Array.isArray(selectedFiles) ? selectedFiles : []) {
    const exactPath = normalizeMatchValue(selectedFile?.absolute_path || selectedFile?.path)
    const candidateMatches = []
    const seenMatches = new Set()
    buildSelectedFileMatchKeys(selectedFile).forEach((key) => {
      for (const candidate of indexedCandidates.get(key) || []) {
        const decisionKey = String(candidate?.decision_key || '').trim()
        if (!decisionKey || seenMatches.has(decisionKey) || seenDecisionKeys.has(decisionKey)) continue
        seenMatches.add(decisionKey)
        candidateMatches.push(candidate)
      }
    })

    candidateMatches.sort((left, right) => {
      const leftExact = Number(normalizeMatchValue(left?.candidate_source_file) === exactPath)
      const rightExact = Number(normalizeMatchValue(right?.candidate_source_file) === exactPath)
      if (rightExact !== leftExact) return rightExact - leftExact
      return String(left?.decision_key || '').localeCompare(String(right?.decision_key || ''))
    })

    const chosenCandidate = candidateMatches[0]
    if (!chosenCandidate) {
      unmatchedSelections.push(selectedFile)
      continue
    }

    const decisionKey = String(chosenCandidate?.decision_key || '').trim()
    seenDecisionKeys.add(decisionKey)
    matchedCandidates.push(chosenCandidate)

    const isResolved = Boolean(chosenCandidate?.resolved) || String(chosenCandidate?.severity || 'clean') === 'clean'
    if (!isResolved) {
      unresolvedCandidates.push(chosenCandidate)
      continue
    }

    const executionItem = buildExecutionItemFromCandidate(chosenCandidate)
    executionItems.push(executionItem)
    if (Object.hasOwn(actionCounts, executionItem.action)) {
      actionCounts[executionItem.action] += 1
    }
  }

  return {
    matchedCandidates,
    executionItems,
    unresolvedCandidates,
    unmatchedSelections,
    actionCounts,
  }
}

export const deriveSubmissionPlan = ({
  selectedCount = 0,
  existingRecordIds = [],
  executionItems = [],
  unresolvedCount = 0,
  unmatchedCount = 0,
} = {}) => {
  const normalizedSelectedCount = Number.isFinite(Number(selectedCount)) ? Math.max(0, Number(selectedCount)) : 0
  const normalizedExistingCount = Array.isArray(existingRecordIds)
    ? existingRecordIds.filter((value) => Number.isInteger(Number(value)) && Number(value) > 0).length
    : 0
  const normalizedExecutionItems = Array.isArray(executionItems)
    ? executionItems.filter((item) => item && typeof item === 'object')
    : []

  if (normalizedSelectedCount === 0) {
    return {
      mode: 'idle',
      selectedCount: 0,
      existingRecordCount: 0,
      recordsToCreateCount: 0,
      title: 'No selection yet',
      description: 'Choose one or more bundles before starting submission.',
      successSummary: 'No records were selected for submission.'
    }
  }

  if (normalizedExecutionItems.length > 0 || unresolvedCount > 0 || unmatchedCount > 0) {
    const actionCounts = normalizedExecutionItems.reduce((summary, item) => {
      const action = String(item?.action || '').trim()
      if (Object.hasOwn(summary, action)) {
        summary[action] += 1
      }
      return summary
    }, {
      create_fresh_record: 0,
      create_version: 0,
      skip: 0,
      force_create_fresh: 0,
    })

    const versionCount = actionCounts.create_version
    const createCount = actionCounts.create_fresh_record
    const forcedCount = actionCounts.force_create_fresh
    const skipCount = actionCounts.skip
    const actionableCount = versionCount + createCount + forcedCount

    let mode = 'record_resolution_plan'
    let title = 'Execute reviewed record plan'
    if (versionCount > 0 && actionableCount === versionCount && skipCount === 0) {
      mode = 'version_records'
      title = 'Create reviewed versions'
    } else if (createCount > 0 && actionableCount === createCount && skipCount === 0) {
      mode = 'create_records'
      title = 'Create records during submit'
    } else if (forcedCount > 0 && actionableCount === forcedCount && skipCount === 0) {
      mode = 'force_create_records'
      title = 'Force fresh record creation'
    } else if (skipCount === normalizedSelectedCount && normalizedSelectedCount > 0) {
      mode = 'skip_selection'
      title = 'Skip selected bundles'
    }

    const descriptionParts = []
    if (versionCount > 0) {
      descriptionParts.push(`${versionCount} ${pluralize(versionCount, 'bundle')} will create version ${pluralize(versionCount, 'draft')}`)
    }
    if (createCount > 0) {
      descriptionParts.push(`${createCount} ${pluralize(createCount, 'bundle')} will create fresh ${pluralize(createCount, 'record')}`)
    }
    if (forcedCount > 0) {
      descriptionParts.push(`${forcedCount} ${pluralize(forcedCount, 'bundle')} will force a fresh record override`)
    }
    if (skipCount > 0) {
      descriptionParts.push(`${skipCount} ${pluralize(skipCount, 'bundle')} will be skipped`)
    }
    if (unresolvedCount > 0) {
      descriptionParts.push(`${unresolvedCount} ${pluralize(unresolvedCount, 'bundle')} still require review`)
    }
    if (unmatchedCount > 0) {
      descriptionParts.push(`${unmatchedCount} selected ${pluralize(unmatchedCount, 'bundle')} could not be matched to a saved record-resolution candidate`)
    }

    const successParts = []
    if (versionCount > 0) {
      successParts.push(`${versionCount} version ${pluralize(versionCount, 'draft')} prepared`)
    }
    if (createCount > 0) {
      successParts.push(`${createCount} fresh local ${pluralize(createCount, 'record')} created`)
    }
    if (forcedCount > 0) {
      successParts.push(`${forcedCount} forced fresh ${pluralize(forcedCount, 'record')} created`)
    }
    if (skipCount > 0) {
      successParts.push(`${skipCount} ${pluralize(skipCount, 'bundle')} skipped`)
    }

    return {
      mode,
      selectedCount: normalizedSelectedCount,
      existingRecordCount: 0,
      recordsToCreateCount: actionableCount,
      executionActionCounts: actionCounts,
      unresolvedCount,
      unmatchedCount,
      title,
      description: descriptionParts.join('. ') || 'Submit will execute the saved record-resolution plan.',
      successSummary: successParts.join('. ') || 'Saved record-resolution plan executed.',
    }
  }

  if (normalizedExistingCount > 0 && normalizedExistingCount === normalizedSelectedCount) {
    return {
      mode: 'reprocess_records',
      selectedCount: normalizedSelectedCount,
      existingRecordCount: normalizedExistingCount,
      recordsToCreateCount: 0,
      title: 'Reprocess existing records',
      description: `All ${normalizedExistingCount} selected ${pluralize(normalizedExistingCount, 'bundle')} already map to canonical local ${pluralize(normalizedExistingCount, 'record')}. Submit will reuse those records instead of creating new ones.`,
      successSummary: `Existing local ${pluralize(normalizedExistingCount, 'record')} reused for reprocessing.`
    }
  }

  if (normalizedExistingCount > 0 && normalizedExistingCount < normalizedSelectedCount) {
    return {
      mode: 'mixed_selection',
      selectedCount: normalizedSelectedCount,
      existingRecordCount: normalizedExistingCount,
      recordsToCreateCount: normalizedSelectedCount,
      title: 'Create records from selected files',
      description: `${normalizedExistingCount} selected ${pluralize(normalizedExistingCount, 'bundle')} already have canonical records, but record reuse only applies when every selected bundle maps cleanly. Submit will therefore create or refresh records from the full selected file set.`,
      successSummary: `Local ${pluralize(normalizedSelectedCount, 'record')} created or refreshed from the selected files.`
    }
  }

  return {
    mode: 'create_records',
    selectedCount: normalizedSelectedCount,
    existingRecordCount: 0,
    recordsToCreateCount: normalizedSelectedCount,
    title: 'Create records during submit',
    description: `This selection has no reusable canonical records yet. Submit will create ${normalizedSelectedCount} local ${pluralize(normalizedSelectedCount, 'record')} from the selected ${pluralize(normalizedSelectedCount, 'bundle')} before the processing pipeline runs.`,
    successSummary: `Local ${pluralize(normalizedSelectedCount, 'record')} created during submit.`
  }
}

export const applyTerminalProgressState = (progress, terminalState, message) => ({
  ...(progress && typeof progress === 'object' ? progress : {}),
  current_stage: terminalState,
  status_message: message || progress?.status_message || '',
})
