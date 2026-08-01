const STORAGE_KEY = 'reviewer_id'

function generateId() {
  const suffix = Math.random().toString(36).slice(2, 8).padEnd(6, '0')
  return `reviewer_${suffix}`
}

/**
 * A stable per-browser reviewer identity. There is no auth in this system, so
 * this is an attribution label for the audit trail, not a security boundary.
 */
export function getReviewerId() {
  try {
    const existing = window.localStorage.getItem(STORAGE_KEY)
    if (existing) return existing
    const created = generateId()
    window.localStorage.setItem(STORAGE_KEY, created)
    return created
  } catch {
    // Private browsing or blocked storage: fall back to a session-only id.
    return generateId()
  }
}
