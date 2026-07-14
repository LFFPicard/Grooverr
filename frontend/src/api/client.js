// Thin fetch wrapper. Relative paths only — the Vite dev server proxies
// /api to the backend (vite.config.js), and in production FastAPI serves
// the built frontend from the same origin, so no base URL is needed.

async function handleResponse(response) {
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      if (body?.detail) detail = body.detail
    } catch {
      // non-JSON error body — fall back to statusText
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  if (response.status === 204) return null
  return response.json()
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  return handleResponse(response)
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: 'POST', body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: (path, body) => request(path, { method: 'PUT', body: JSON.stringify(body) }),
  del: (path) => request(path, { method: 'DELETE' }),
  // No Content-Type here — the browser sets multipart/form-data with the
  // correct boundary itself when the body is a FormData instance.
  upload: async (path, formData) => handleResponse(await fetch(path, { method: 'POST', body: formData })),
}
