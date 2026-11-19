export function pendingGpuMessage(allocation) {
  if (allocation?.status === 'queued') {
    return 'Your GPU request is queued in WebHDP.'
  }
  if (allocation?.reservation_id) return 'Waiting for HPC-Link to confirm the reserved GPU.'
  if (allocation?.scheduler_reason === 'Resources') {
    return 'Waiting for a GPU. The scheduler has no matching resources available for this request yet.'
  }
  if (allocation?.scheduler_reason === 'Priority') {
    return 'Waiting for a GPU. The scheduler is prioritizing other jobs.'
  }
  return 'Waiting for the scheduler to assign a GPU.'
}
