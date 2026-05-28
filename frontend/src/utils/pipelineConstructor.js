function deepClone(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value))
}

function omitKeys(source, keys) {
  if (!source || typeof source !== 'object' || Array.isArray(source)) {
    return {}
  }
  const keySet = new Set(keys)
  return Object.fromEntries(Object.entries(source).filter(([key]) => !keySet.has(key)))
}

const STRUCTURED_TRIGGER_ROOT_KEYS = ['default_behavior', 'rules']
const STRUCTURED_TRIGGER_RULE_KEYS = ['id', 'label', 'action', 'conditions', 'parameter_overrides']
const STRUCTURED_TRIGGER_CONDITION_KEYS = ['source_type', 'source_step', 'source_output', 'field', 'operator', 'value', 'values']

export function buildOutputActionSourceKey(action) {
  return JSON.stringify({
    action_type: action.action_type,
    source_output: action.source_output,
    selector: action.selector,
    target_field: action.target_field,
    transform: action.transform,
    overwrite_policy: action.overwrite_policy,
  })
}

export function extractAdvancedTriggerPayload(triggers = {}) {
  return omitKeys(triggers, STRUCTURED_TRIGGER_ROOT_KEYS)
}

export function buildAdvancedJsonPayload(rawStep, structuredInputBindingTargets, structuredOutputMappings) {
  const structuredTargets = new Set(structuredInputBindingTargets)
  const structuredOutputKeys = new Set(structuredOutputMappings.map((mapping) => mapping.__sourceKey))
  return JSON.stringify(
    {
      input_bindings: (rawStep.input_bindings || []).filter((binding) => !structuredTargets.has(binding.target)),
      parameter_bindings: rawStep.parameter_bindings || [],
      output_actions: (rawStep.output_actions || []).filter((action) => !structuredOutputKeys.has(buildOutputActionSourceKey(action))),
      resources: rawStep.resources || {},
      triggers: extractAdvancedTriggerPayload(rawStep.triggers || {}),
    },
    null,
    2
  )
}

export function normalizeTriggerRule(rule = {}, nextLocalKey) {
  return {
    localKey: nextLocalKey('rule'),
    id: rule.id || 'rule',
    label: rule.label || '',
    action: rule.action || 'run',
    conditions: (rule.conditions || []).map((condition) => ({
      localKey: nextLocalKey('condition'),
      source_type: condition.source_type || 'file_fact',
      source_step: condition.source_step || '',
      source_output: condition.source_output || '',
      field: condition.field || '',
      operator: condition.operator || 'eq',
      value_text: Array.isArray(condition.values)
        ? condition.values.join(', ')
        : condition.value !== undefined && condition.value !== null
          ? String(condition.value)
          : '',
      value_from: Array.isArray(condition.values) ? String(condition.values[0] ?? '') : '',
      value_to: Array.isArray(condition.values) ? String(condition.values[1] ?? '') : '',
      __advanced: omitKeys(condition, STRUCTURED_TRIGGER_CONDITION_KEYS),
    })),
    parameterOverrideRows: Object.entries(rule.parameter_overrides || {}).map(([name, value]) => ({
      localKey: nextLocalKey('override'),
      name,
      value,
    })),
    __advanced: omitKeys(rule, STRUCTURED_TRIGGER_RULE_KEYS),
  }
}

export function serializeTriggerCondition(condition, payload) {
  return {
    ...deepClone(condition?.__advanced || {}),
    ...payload,
  }
}

export function serializeTriggerRule(rule, conditions, parameterOverrides) {
  return {
    ...deepClone(rule?.__advanced || {}),
    id: rule.id,
    label: rule.label || undefined,
    action: rule.action || 'run',
    conditions,
    parameter_overrides: parameterOverrides,
  }
}

function isJsonCompatibleFieldType(fieldType) {
  return !['file_path', 'file_list', 'dir_path'].includes(fieldType)
}

export function getCompatiblePreviousOutput(field, earlierSteps) {
  const matches = []
  ;(earlierSteps || []).forEach((step) => {
    ;(step.outputs || []).forEach((output) => {
      if (field.type === 'file_path' && output.type === 'file_path') {
        matches.push({ type: 'artifact_file', source_step: step.id, source_output: output.name })
      }
      if (field.type === 'file_list' && ['file_path', 'dir_path'].includes(output.type)) {
        matches.push({ type: output.type === 'dir_path' ? 'artifact_directory' : 'artifact_file', source_step: step.id, source_output: output.name })
      }
      if (field.type === 'dir_path' && output.type === 'dir_path') {
        matches.push({ type: 'artifact_directory', source_step: step.id, source_output: output.name })
      }
      if (isJsonCompatibleFieldType(field.type) && ['json', 'file_path'].includes(output.type)) {
        matches.push({ type: 'artifact_json_value', source_step: step.id, source_output: output.name })
      }
    })
  })
  return matches.length === 1 ? matches[0] : null
}

export function buildDefaultBindingForField(field, earlierSteps) {
  const previousOutput = getCompatiblePreviousOutput(field, earlierSteps)
  if (previousOutput) {
    return {
      enabled: true,
      target: field.name,
      type: previousOutput.type,
      source_step: previousOutput.source_step,
      source_output: previousOutput.source_output,
      selector: '',
    }
  }
  if (field.type === 'file_path') {
    return { enabled: true, target: field.name, type: 'pipeline_source_file', source_step: '', source_output: '', selector: '' }
  }
  if (field.type === 'file_list') {
    return { enabled: true, target: field.name, type: 'pipeline_source_files', source_step: '', source_output: '', selector: '' }
  }
  if (field.type === 'dir_path') {
    return { enabled: true, target: field.name, type: 'pipeline_source_directory', source_step: '', source_output: '', selector: '' }
  }
  return { enabled: false, target: field.name, type: '', source_step: '', source_output: '', selector: '' }
}

export function getCompatibleSourceOutputOptions(field, outputs) {
  return (outputs || [])
    .filter((output) => {
      if (field.type === 'file_path') {
        return output.type === 'file_path'
      }
      if (field.type === 'file_list') {
        return ['file_path', 'dir_path'].includes(output.type)
      }
      if (field.type === 'dir_path') {
        return output.type === 'dir_path'
      }
      return ['json', 'file_path'].includes(output.type)
    })
    .map((output) => ({ value: output.name, label: output.label || output.name }))
}
