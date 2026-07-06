// =============================================================================
// js/api.js
// -----------------------------------------------------------------------------
// Pure networking layer. Nothing in this file knows about the DOM, forms, or
// which page it's running on -- it only knows how to reach the FastAPI
// backend and how to attach the current session's Authorization header.
//
// Every other module imports `apiRequest` (or `API_URL` directly, for the
// one raw-blob download in components/audit.js) from here instead of calling
// `fetch()` itself, so there's exactly one place that knows the backend's
// base URL and exactly one place that knows how 401s should be handled.
// =============================================================================

import { getSession, logout } from './auth.js';

export const API_URL = 'http://127.0.0.1:8000'; // Change to your FastAPI backend URL if different

// Small fetch wrapper that automatically attaches the Authorization header
// and JSON-parses the response, throwing a readable Error on failure.
export async function apiRequest(path, options = {}) {
  const session = getSession();
  const headers = Object.assign({}, options.headers || {});
  if (session) headers['Authorization'] = `Bearer ${session.token}`;
  // Don't force a JSON content-type when sending FormData (CSV upload) --
  // the browser needs to set its own multipart boundary header for that.
  if (!(options.body instanceof FormData) && options.body) {
    headers['Content-Type'] = 'application/json';
  }

  const response = await fetch(`${API_URL}${path}`, { ...options, headers });

  if (response.status === 401) {
    // Session expired or invalid -- force a clean re-login.
    logout();
    throw new Error('Your session has expired. Please log in again.');
  }

  // Some endpoints (CSV export) return a raw file, not JSON.
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    if (!response.ok) throw new Error('Request failed.');
    return response;
  }

  const data = await response.json();
  if (!response.ok) {
    throw new Error(formatErrorDetail(data.detail));
  }
  return data;
}

// FastAPI returns `detail` as a plain string for most errors (e.g. our own
// `raise HTTPException(status_code=400, detail="...")` calls), but as an
// ARRAY of {loc, msg, type} objects for Pydantic validation failures (422s)
// -- e.g. the password-strength or due-date validators in schemas/*.py.
// Without this, `new Error(anArray)` would stringify to something useless
// like "[object Object]" instead of the actual validation message.
function formatErrorDetail(detail) {
  if (!detail) return 'Request failed.';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (item && typeof item === 'object' && 'msg' in item ? item.msg : String(item)))
      .join(' ');
  }
  return 'Request failed.';
}
