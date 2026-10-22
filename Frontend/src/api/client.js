/**
 * All network calls go through the Node.js + Express API gateway.
 * This module never talks to the Python FastAPI ML service directly.
 */
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

function generateRequestId() {
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
export function uploadCsvForAnalysis(file, { onProgress, objectId } = {}) {
  const requestId = generateRequestId();

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/api/v1/predict`);
    xhr.setRequestHeader("X-Request-Id", requestId);

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
  const response = await fetch(`${API_BASE_URL}/api/v1/feature-schema`);
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw body?.error || { code: "UNKNOWN_ERROR", message: "Could not load the parameter schema." };
  }
  return body;
}

/** Submits manually-entered named model parameters to POST /api/v1/predict/manual. */
export async function submitManualParameters(namedParams) {
  const requestId = generateRequestId();
  const response = await fetch(`${API_BASE_URL}/api/v1/predict/manual`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Request-Id": requestId },
    body: JSON.stringify(namedParams),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
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
    headers: { "Content-Type": "application/json", "X-Request-Id": requestId },
    body: JSON.stringify({ ...namedParams, object_id: objectId }),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
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
    headers: { "Content-Type": "application/json", "X-Request-Id": requestId },
    body: JSON.stringify(body),
  });
  const parsed = await response.json().catch(() => null);
  if (!response.ok) {
    throw parsed?.error || { code: "UNKNOWN_ERROR", message: "The characterization request failed." };
  }
  return parsed;
}
