import { describe, expect, test, vi, beforeEach, afterEach } from "vitest";
import { uploadCsvForAnalysis, recomputeCharacterization } from "../src/api/client";

class FakeXHR {
  constructor() {
    this.upload = {};
    this.requestHeaders = {};
  }
  open(method, url) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(key, value) {
    this.requestHeaders[key] = value;
  }
  send(body) {
    this.sentBody = body;
    FakeXHR.instances.push(this);
  }
}
FakeXHR.instances = [];

describe("uploadCsvForAnalysis", () => {
  let originalXHR;

  beforeEach(() => {
    originalXHR = global.XMLHttpRequest;
    FakeXHR.instances = [];
    global.XMLHttpRequest = FakeXHR;
  });

  afterEach(() => {
    global.XMLHttpRequest = originalXHR;
  });

  test("resolves with parsed JSON body on a 200 response", async () => {
    const file = new File(["a,b\n1,2"], "test.csv", { type: "text/csv" });
    const promise = uploadCsvForAnalysis(file);

    const xhr = FakeXHR.instances[0];
    xhr.status = 200;
    xhr.responseText = JSON.stringify({ prediction: "ok", total_rows: 1 });
    xhr.onload();

    await expect(promise).resolves.toEqual({ prediction: "ok", total_rows: 1 });
    expect(xhr.requestHeaders["X-Request-Id"]).toBeTruthy();
  });

  test("rejects with the structured error on a non-2xx response", async () => {
    const file = new File(["bad"], "test.csv", { type: "text/csv" });
    const promise = uploadCsvForAnalysis(file);

    const xhr = FakeXHR.instances[0];
    xhr.status = 422;
    xhr.responseText = JSON.stringify({ error: { code: "CSV_VALIDATION_ERROR", message: "bad csv" } });
    xhr.onload();

    await expect(promise).rejects.toEqual({ code: "CSV_VALIDATION_ERROR", message: "bad csv" });
  });

  test("rejects with NETWORK_ERROR when the request fails outright", async () => {
    const file = new File(["x"], "test.csv", { type: "text/csv" });
    const promise = uploadCsvForAnalysis(file);

    const xhr = FakeXHR.instances[0];
    xhr.onerror();

    await expect(promise).rejects.toEqual({
      code: "NETWORK_ERROR",
      message: "Could not reach the backend. Is it running?",
    });
  });

  test("object_id is included in the form data when supplied", async () => {
    const file = new File(["a,b\n1,2"], "test.csv", { type: "text/csv" });
    const promise = uploadCsvForAnalysis(file, { objectId: "K00752.01" });

    const xhr = FakeXHR.instances[0];
    expect(xhr.sentBody.get("object_id")).toBe("K00752.01");

    xhr.status = 200;
    xhr.responseText = JSON.stringify({});
    xhr.onload();
    await promise;
  });

  test("object_id is still sent as an empty string when not supplied (required field, backend validates)", async () => {
    const file = new File(["a,b\n1,2"], "test.csv", { type: "text/csv" });
    const promise = uploadCsvForAnalysis(file);

    const xhr = FakeXHR.instances[0];
    expect(xhr.sentBody.get("object_id")).toBe("");

    xhr.status = 200;
    xhr.responseText = JSON.stringify({});
    xhr.onload();
    await promise;
  });

  test("reports upload progress via onProgress callback", async () => {
    const file = new File(["x"], "test.csv", { type: "text/csv" });
    const onProgress = vi.fn();
    const promise = uploadCsvForAnalysis(file, { onProgress });

    const xhr = FakeXHR.instances[0];
    xhr.upload.onprogress({ lengthComputable: true, loaded: 50, total: 100 });
    expect(onProgress).toHaveBeenCalledWith(50);

    xhr.status = 200;
    xhr.responseText = JSON.stringify({});
    xhr.onload();
    await promise;
  });
});

describe("recomputeCharacterization", () => {
  let originalFetch;
  beforeEach(() => { originalFetch = global.fetch; });
  afterEach(() => { global.fetch = originalFetch; });

  test("posts the snapshot, overrides, config and form edits to the gateway", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "complete" }) });
    const edits = { submitted: { koi_srad: 1.1 }, automatic: { koi_srad: 0.927 } };
    const body = await recomputeCharacterization({
      inputs: { schema_version: 1 }, overrides: { planet_mass: 5 }, config: { bond_albedo: 0 }, modelFeatureEdits: edits,
    });
    expect(body.status).toBe("complete");
    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toContain("/api/v1/characterization/recompute");
    expect(options.method).toBe("POST");
    expect(options.headers["X-Request-Id"]).toBeTruthy();
    expect(JSON.parse(options.body)).toEqual({
      inputs: { schema_version: 1 }, overrides: { planet_mass: 5 }, config: { bond_albedo: 0 }, model_feature_edits: edits,
    });
  });

  test("surfaces the backend's structured error", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false, json: async () => ({ error: { code: "CHARACTERIZATION_VALIDATION_ERROR", message: "bad" } }),
    });
    await expect(recomputeCharacterization({ inputs: {} })).rejects.toEqual({
      code: "CHARACTERIZATION_VALIDATION_ERROR", message: "bad",
    });
  });
});
