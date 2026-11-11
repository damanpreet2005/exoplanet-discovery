/**
 * All network calls go through the Node.js + Express API gateway.
 * This module never talks to the Python FastAPI ML service directly.
 */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

/**
 * Analysis endpoints require a signed-in user. AuthContext registers how to
 * obtain the current in-memory access token (never stored in web storage):
 *   peek()           -> a fresh token synchronously, or null
 *   get()            -> Promise<token>, refreshing the session if needed
 *   onUnauthorized() -> called on a 401 so the session can refresh or end
 */
let authTokenProvider = null;

export function setAuthTokenProvider(provider) {
  authTokenProvider = provider;
}

async function authHeaders() {
  if (!authTokenProvider) return {};
  try {
    const token = await authTokenProvider.get();
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    // No session: send the request anyway and let the gateway answer 401.
    return {};
  }
}

function noteUnauthorized(status) {
  if (status === 401 && authTokenProvider) authTokenProvider.onUnauthorized();
}

export function generateRequestId() {
  if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
  return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * Uploads a light-curve CSV (time, flux columns -- nothing else required) to
 * POST /api/v1/predict, via XMLHttpRequest (rather than fetch) specifically
 * so we get real upload-progress events to drive the progress bar -- not a
 * simulated/fake progress animation.
 *
 * `objectId` is the required astronomical catalog Object ID (e.g.
 * "KIC 11904151", "K00752.01", or "Kepler-227 b") for the star/object this
 * light curve belongs to -- the RF's trained features include catalog-only
 * stellar fields a light curve alone cannot supply, so this is required
 * alongside the CSV, not an optional extra.
 */
export function uploadCsvForAnalysis(file, options = {}) {
  // Start the upload synchronously when a fresh token is already in memory
  // (the usual case); otherwise refresh the session first.
  const token = authTokenProvider ? authTokenProvider.peek() : null;
  if (authTokenProvider && !token) {
    return authHeaders().then((headers) => sendCsvUpload(file, options, headers.Authorization));
  }
  return sendCsvUpload(file, options, token ? `Bearer ${token}` : null);
}

function sendCsvUpload(file, { onProgress, objectId } = {}, authorization) {
  const requestId = generateRequestId();

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/api/v1/predict`);
    xhr.setRequestHeader("X-Request-Id", requestId);
    if (authorization) xhr.setRequestHeader("Authorization", authorization);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      let body;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        reject({ code: "PARSE_ERROR", message: "The server returned an unreadable response." });
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body);
      } else {
        noteUnauthorized(xhr.status);
        reject(body?.error || { code: "UNKNOWN_ERROR", message: "The analysis request failed." });
      }
    };

    xhr.onerror = () => {
      reject({ code: "NETWORK_ERROR", message: "Could not reach the backend. Is it running?" });
    };

    const formData = new FormData();
    formData.append("file", file);
    formData.append("object_id", (objectId || "").trim());
    xhr.send(formData);
  });
}

async function fetchJson(path, { timeoutMs = 5000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, { signal: controller.signal });
    return { ok: response.ok, body: await response.json().catch(() => null) };
  } catch {
    return { ok: false, body: null };
  } finally {
    clearTimeout(timer);
  }
}

export function getGatewayHealth() {
  return fetchJson("/api/v1/health");
}

export function getGatewayReadiness() {
  return fetchJson("/api/v1/ready");
}

/** Feature display metadata (canonical name, label, unit, aliases) for the
 * manual-parameter form -- fetched from the backend so the UI never
 * hardcodes a second copy of the feature list. */
export async function fetchFeatureSchema() {
  const response = await fetch(`${API_BASE_URL}/api/v1/feature-schema`, { headers: await authHeaders() });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    noteUnauthorized(response.status);
    throw body?.error || { code: "UNKNOWN_ERROR", message: "Could not load the parameter schema." };
  }
  return body;
}

/**
 * Submits manually-entered named model parameters to POST /api/v1/predict/manual.
 * `historyId` (the CSV run's `history_id` from POST /predict) tells the gateway
 * which saved run these parameters belong to; it is sent as a header so the
 * parameter body stays exactly the named values.
 */
export async function submitManualParameters(namedParams, historyId) {
  const requestId = generateRequestId();
  const headers = { "Content-Type": "application/json", "X-Request-Id": requestId, ...(await authHeaders()) };
  if (historyId) headers["X-History-Id"] = historyId;
  const response = await fetch(`${API_BASE_URL}/api/v1/predict/manual`, {
    method: "POST",
    headers,
    body: JSON.stringify(namedParams),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    noteUnauthorized(response.status);
    throw body?.error || { code: "UNKNOWN_ERROR", message: "The prediction request failed." };
  }
  return body;
}

/**
 * Stage 2: submits the candidate's named KOI parameters (plus an optional
 * object_id, echoed back for display) to POST /api/v1/physics-validation
 * and returns the real backend-computed report. Never fabricated client-side.
 */
export async function runPhysicsValidation(namedParams, objectId) {
  const requestId = generateRequestId();
  const response = await fetch(`${API_BASE_URL}/api/v1/physics-validation`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Request-Id": requestId, ...(await authHeaders()) },
    body: JSON.stringify({ ...namedParams, object_id: objectId }),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    noteUnauthorized(response.status);
    throw body?.error || { code: "UNKNOWN_ERROR", message: "The physics validation request failed." };
  }
  return body;
}

/**
 * Re-runs the planet characterization engine on the report's stored
 * `inputs` snapshot with expert overrides and/or changed assumptions, via
 * POST /api/v1/characterization/recompute. No light-curve refit happens; the
 * backend returns a complete new report. Never computed client-side.
 *
 * `modelFeatureEdits` ({submitted, automatic}) forwards edits made in the
 * 17-parameter Expert Override form; the backend converts the fields that
 * actually changed into characterization overrides.
 */
export async function recomputeCharacterization({ inputs, overrides, config, modelFeatureEdits }) {
  const requestId = generateRequestId();
  const body = { inputs, overrides: overrides || {}, config: config || {} };
  if (modelFeatureEdits) body.model_feature_edits = modelFeatureEdits;
  const response = await fetch(`${API_BASE_URL}/api/v1/characterization/recompute`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Request-Id": requestId, ...(await authHeaders()) },
    body: JSON.stringify(body),
  });
  const parsed = await response.json().catch(() => null);
  if (!response.ok) {
    noteUnauthorized(response.status);
    throw parsed?.error || { code: "UNKNOWN_ERROR", message: "The characterization request failed." };
  }
  return parsed;
}

/** The signed-in user's saved prediction runs, newest first, from GET /api/v1/history. */
export async function fetchPredictionHistory() {
  const response = await fetch(`${API_BASE_URL}/api/v1/history`, { headers: await authHeaders() });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    noteUnauthorized(response.status);
    throw body?.error || { code: "UNKNOWN_ERROR", message: "Could not load your prediction history." };
  }
  return body;
}

/** Fetches a saved run's uploaded CSV, by its stored GridFS file id, as a Blob. */
export async function fetchPredictionCsv(fileId) {
  const response = await fetch(`${API_BASE_URL}/api/v1/history/csv/${encodeURIComponent(fileId)}`, {
    headers: { "X-Request-Id": generateRequestId(), ...(await authHeaders()) },
  });
  if (!response.ok) {
    noteUnauthorized(response.status);
    const body = await response.json().catch(() => null);
    throw body?.error || { code: "UNKNOWN_ERROR", message: "Could not load the saved CSV." };
  }
  return response.blob();
}

/**
 * Downloads a saved run's uploaded CSV via GET /api/v1/history/csv/:fileId.
 * The request carries the Bearer token, so the file is fetched as a Blob and
 * saved through a temporary object URL rather than by navigating to the
 * endpoint.
 */
export async function downloadPredictionCsv(fileId, filename) {
  const blob = await fetchPredictionCsv(fileId);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename || "prediction.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/**
 * Renames a saved prediction via PATCH /api/v1/history/:id. An empty name
 * restores the default (catalogue) name. Returns the updated record.
 */
export async function renamePrediction(historyId, name) {
  const response = await fetch(`${API_BASE_URL}/api/v1/history/${encodeURIComponent(historyId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", "X-Request-Id": generateRequestId(), ...(await authHeaders()) },
    body: JSON.stringify({ name }),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    noteUnauthorized(response.status);
    throw body?.error || { code: "UNKNOWN_ERROR", message: "Could not rename the prediction." };
  }
  return body.run;
}
