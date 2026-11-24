// All calls to the FastAPI backend live in this file.

// Set at build time (Vite reads VITE_* variables). Trailing "/" removed.
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '')

// Error with the HTTP status attached, so the UI can show "Error 503" etc.
export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

// POST /chat -> { session_id, reply, metadata }
export async function sendChat({ sessionId, message, systemPrompt, simulate }) {
  const body = { session_id: sessionId, message }
  if (systemPrompt.trim()) body.system_prompt = systemPrompt

  const headers = { 'Content-Type': 'application/json' }
  if (simulate) headers['X-Simulate-Failure'] = simulate // failover test hook

  let response
  try {
    response = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    })
  } catch {
    // fetch only throws when there is no HTTP response at all (server down, CORS, offline)
    throw new ApiError(
      null,
      `Could not reach the server at ${API_BASE_URL}. Check that the backend is running and try again.`,
    )
  }

  const data = await readJson(response)
  if (!response.ok) {
    throw new ApiError(response.status, describeError(response.status, data?.detail))
  }
  if (typeof data?.reply !== 'string' || !data.metadata) {
    throw new ApiError(response.status, 'The server sent a response in an unexpected format.')
  }
  return data
}

// GET /health -> { status, keys_configured, cache_enabled } or null when unreachable
export async function checkHealth() {
  try {
    // Give up after 10 s so a hanging request (cold start) doesn't block the next retry
    const response = await fetch(`${API_BASE_URL}/health`, { signal: AbortSignal.timeout(10000) })
    return response.ok ? await response.json() : null
  } catch {
    return null
  }
}

// The body may not be JSON (e.g. an HTML page from a proxy), so never let this throw
async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

// Turn a status + FastAPI "detail" into one sentence a user can read
function describeError(status, detail) {
  if (status === 422) {
    return describeValidation(detail)
  }
  if (status === 503) {
    return 'All AI providers are unavailable right now (every API key failed). Your message was not saved. Please try again in a moment.'
  }
  const text = typeof detail === 'string' ? detail : 'unexpected server error'
  return `The server could not answer: ${text}.`
}

const FIELD_NAMES = {
  message: 'Message',
  session_id: 'Session id',
  system_prompt: 'System prompt',
}

// 422 detail is either a string (our own errors) or FastAPI's list of field errors
function describeValidation(detail) {
  if (typeof detail === 'string') return capitalize(detail) + '.'
  if (!Array.isArray(detail) || detail.length === 0) return 'The request was not valid.'

  return detail
    .map((error) => {
      const field = FIELD_NAMES[error.loc?.at(-1)] ?? 'Request'
      if (error.type === 'string_too_short') return `${field} cannot be empty.`
      if (error.type === 'string_too_long') {
        return `${field} is too long (maximum ${error.ctx?.max_length} characters).`
      }
      if (error.type === 'missing') return `${field} is required.`
      return `${field}: ${error.msg}.`
    })
    .join(' ')
}

function capitalize(text) {
  return text.charAt(0).toUpperCase() + text.slice(1)
}
