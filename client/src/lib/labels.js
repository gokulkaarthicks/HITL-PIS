export const SEVERITIES = ['critical', 'high', 'medium', 'low']

export const COMPONENTS = [
  'frontend',
  'backend',
  'mobile',
  'auth',
  'payments',
  'database',
  'infrastructure',
  'unknown',
]

/* Keep severity legible without turning the interface into a rainbow. */
export const SEVERITY_STYLES = {
  critical: 'text-ansi-red',
  high: 'text-ansi-orange',
  medium: 'text-ansi-yellow',
  low: 'text-term-dim',
}

export const STATUS_LABELS = {
  new: 'not run',
  llm_run: 'awaiting review',
  reviewed: 'reviewed',
}

export const STATUS_STYLES = {
  new: 'text-term-faint',
  llm_run: 'text-ansi-green',
  reviewed: 'text-ansi-green',
}

export const formatPercent = (value) =>
  value == null ? '--' : `${(value * 100).toFixed(1)}%`

export const formatDelta = (value) => {
  if (value == null) return '--'
  const points = value * 100
  const sign = points > 0 ? '+' : ''
  return `${sign}${points.toFixed(1)} pts`
}

/** Timestamps render in a sortable, terminal-log shape: YYYY-MM-DD HH:MM. */
export const formatTimestamp = (value) => {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  const pad = (n) => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`
  )
}
