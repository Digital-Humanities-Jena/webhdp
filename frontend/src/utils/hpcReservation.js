export const reservationStatusLabel = (status) => ({
  available: 'Available',
  in_use: 'In use',
  expired: 'Expired',
  unavailable: 'Unavailable',
  disabled: 'Disabled',
})[status] || 'Unavailable'

export function reservationHardware(reservation) {
  const gpu = reservation.gpu_count
    ? `${reservation.gpu_count} ${reservation.gpu_type?.toUpperCase() || 'GPU'}`
    : null
  const cpu = reservation.cpus ? `${reservation.cpus} CPUs` : null
  const ram = reservation.memory_mb ? `${Number((reservation.memory_mb / 1024).toFixed(1))} GiB RAM` : null
  return [gpu, cpu, ram].filter(Boolean).join(' · ')
}

export function reservationExpiry(expiresAt, now = Date.now()) {
  const end = Date.parse(expiresAt)
  if (!Number.isFinite(end)) return null
  const minutes = Math.floor((end - now) / 60000)
  if (end <= now) return { expired: true, label: 'Expired' }
  if (minutes < 1) return { expired: false, label: 'Less than 1 min left' }
  const hours = Math.floor(minutes / 60)
  const left = hours ? `${hours} h ${minutes % 60} min` : `${minutes} min`
  return { expired: false, label: `${left} left` }
}
