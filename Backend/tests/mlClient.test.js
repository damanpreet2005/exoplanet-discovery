/**
 * Retry policy of the CSV-analysis call: transient connection failures are
 * retried, but a timeout is not -- the ML service keeps computing the aborted
 * request, so retrying would multiply CPU-bound work (a retry storm).
 */
process.env.ML_SERVICE_MAX_RETRIES = "2";
process.env.ML_SERVICE_RETRY_BACKOFF_SECONDS = "0";
process.env.ML_SERVICE_ANALYSIS_TIMEOUT = "0.05";
const mlClient = require("../src/services/mlClient");
const { MLServiceTimeoutError } = require("../src/errors");

const ARGS = { buffer: Buffer.from("time,flux\n0,1\n"), filename: "lc.csv", mimetype: "text/csv", requestId: "r1", objectId: "K00752.01" };

afterEach(() => { global.fetch = undefined; });

test("a timed-out analysis is not retried", async () => {
  global.fetch = jest.fn((url, { signal }) => new Promise((_, reject) => {
    signal.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })));
  }));
  await expect(mlClient.forwardCsvPrediction(ARGS)).rejects.toBeInstanceOf(MLServiceTimeoutError);
  expect(global.fetch).toHaveBeenCalledTimes(1);
});

test("a connection failure is still retried", async () => {
  global.fetch = jest.fn()
    .mockRejectedValueOnce(new TypeError("fetch failed"))
    .mockResolvedValueOnce({ ok: true, json: async () => ({ ok: 1 }) });
  await expect(mlClient.forwardCsvPrediction(ARGS)).resolves.toEqual({ ok: 1 });
  expect(global.fetch).toHaveBeenCalledTimes(2);
});
