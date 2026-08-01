const BASE_URL = (
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
).replace(/\/$/, '')

/**
 * Thin fetch wrapper. The backend always reports failures as {"detail": "..."},
 * so surface that text directly instead of a generic "request failed".
 */
async function request(path, { method = 'GET', body, headers } = {}) {
  let response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: {
        ...headers,
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new Error(
      `Cannot reach the API at ${BASE_URL}. Is the backend running?`,
    )
  }

  if (response.status === 204) return null

  const text = await response.text()
  const payload = text ? safeParse(text) : null

  if (!response.ok) {
    throw new Error(detailOf(payload) || `${response.status} ${response.statusText}`)
  }
  return payload
}

function safeParse(text) {
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

/** FastAPI returns `detail` as a string, or as a list for validation errors. */
function detailOf(payload) {
  if (!payload || typeof payload !== 'object') return null
  const { detail } = payload
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
  }
  return null
}

/**
 * Read a newline-delimited JSON stream, invoking `onEvent` per line.
 *
 * `EventSource` cannot issue a POST, so this reads the response body directly.
 * Lines can be split across chunks, so the trailing partial line is carried
 * over rather than parsed.
 */
async function requestNdjson(path, { onEvent }) {
  let response
  try {
    response = await fetch(`${BASE_URL}${path}`, { method: 'POST' })
  } catch {
    throw new Error(
      `Cannot reach the API at ${BASE_URL}. Is the backend running?`,
    )
  }

  if (!response.ok) {
    const text = await response.text()
    throw new Error(
      detailOf(safeParse(text)) || `${response.status} ${response.statusText}`,
    )
  }

  const reader = response.body?.getReader()
  if (!reader) throw new Error('Streaming is not supported by this browser.')

  const decoder = new TextDecoder()
  let buffer = ''

  const handle = (line) => {
    if (!line.trim()) return
    onEvent(JSON.parse(line))
  }

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    lines.forEach(handle)
  }
  handle(buffer)
}

export const api = {
  health: () => request('/health'),

  listBugs: () => request('/bugs'),
  createBug: (reportText) =>
    request('/bugs', { method: 'POST', body: { report_text: reportText } }),
  runLlm: (bugId, reviewerId) =>
    request(`/bugs/${bugId}/run`, {
      method: 'POST',
      body: { reviewer_id: reviewerId },
    }),
  saveCorrection: (bugId, corrected, reviewerId) =>
    request(`/bugs/${bugId}/correction`, {
      method: 'PUT',
      body: { corrected, reviewer_id: reviewerId },
    }),

  listPrompts: () => request('/prompts'),
  activePrompt: () => request('/prompts/active'),
  improvePrompt: () => request('/prompts/improve', { method: 'POST' }),

  evalExamples: () => request('/eval/examples'),
  runEvaluation: ({ force = false } = {}) =>
    request(`/eval/run${force ? '?force=true' : ''}`, { method: 'POST' }),

  /**
   * Streaming variant. Calls `onProgress({completed, total, arm})` as examples
   * finish and resolves with the same comparison object as `runEvaluation`.
   */
  runEvaluationStream: async (onProgress, { force = false } = {}) => {
    let result = null
    let failure = null

    await requestNdjson(`/eval/run/stream${force ? '?force=true' : ''}`, {
      onEvent: (event) => {
        if (event.type === 'progress') onProgress?.(event)
        else if (event.type === 'result') result = event.result
        else if (event.type === 'error') failure = event.detail
      },
    })

    if (failure) throw new Error(failure)
    if (!result) throw new Error('Evaluation ended without returning a result.')
    return result
  },

  latestEvaluation: () => request('/eval/latest'),

  resetDemo: () =>
    request('/admin/reset', {
      method: 'POST',
      body: { confirmation: 'RESET' },
    }),
}
