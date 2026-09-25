import { describe, expect, test, vi, beforeEach, afterEach } from "vitest";
import { uploadCsvForAnalysis } from "../src/api/client";

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
  send() {
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
