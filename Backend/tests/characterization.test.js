jest.mock("../src/services/mlClient");
const mlClient = require("../src/services/mlClient");
const request = require("supertest");
const { createApp } = require("../src/app");
const { MLServiceUnavailableError, MLServiceTimeoutError, UpstreamValidationError } = require("../src/errors");

const app = createApp();

const INPUTS = { schema_version: 1, transit_fit: { status: "fitted" }, catalog: {} };
const FAKE_REPORT = { status: "complete", parameters: { planet_radius: { value: 2.3 } }, inputs: INPUTS };

afterEach(() => jest.clearAllMocks());

describe("POST /api/v1/characterization/recompute", () => {
  test("forwards inputs and overrides unchanged to the ML service", async () => {
    mlClient.forwardCharacterizationRecompute.mockResolvedValue({ ...FAKE_REPORT });
    const body = { inputs: INPUTS, overrides: { stellar_radius: 1.1 }, config: { bond_albedo: 0.3 } };

    const res = await request(app).post("/api/v1/characterization/recompute").set("X-Request-Id", "trace-c1").send(body);

    expect(res.status).toBe(200);
    expect(res.body.status).toBe("complete");
    expect(res.body.request_id).toBe("trace-c1");
    expect(mlClient.forwardCharacterizationRecompute).toHaveBeenCalledWith(body, "trace-c1");
  });

  test("missing inputs snapshot returns 422 without calling the ML service", async () => {
    const res = await request(app).post("/api/v1/characterization/recompute").send({ overrides: {} });
    expect(res.status).toBe(422);
    expect(res.body.error.code).toBe("VALIDATION_ERROR");
    expect(mlClient.forwardCharacterizationRecompute).not.toHaveBeenCalled();
  });

  test("non-object overrides are rejected", async () => {
    const res = await request(app).post("/api/v1/characterization/recompute").send({ inputs: INPUTS, overrides: [1] });
    expect(res.status).toBe(422);
    expect(mlClient.forwardCharacterizationRecompute).not.toHaveBeenCalled();
  });

  test("accepts a realistic snapshot larger than the default 100kb JSON limit", async () => {
    mlClient.forwardCharacterizationRecompute.mockResolvedValue({ ...FAKE_REPORT });
    const big = { ...INPUTS, transit_fit: { status: "fitted", transit_times: "x".repeat(200000) } };
    const res = await request(app).post("/api/v1/characterization/recompute").send({ inputs: big });
    expect(res.status).toBe(200);
  });

  test("upstream override validation errors are passed through", async () => {
    mlClient.forwardCharacterizationRecompute.mockRejectedValue(
      new UpstreamValidationError(422, { error: { code: "CHARACTERIZATION_VALIDATION_ERROR", message: "out of range" } })
    );
    const res = await request(app).post("/api/v1/characterization/recompute").send({ inputs: INPUTS, overrides: { stellar_radius: -1 } });
    expect(res.status).toBe(422);
    expect(res.body.error.code).toBe("CHARACTERIZATION_VALIDATION_ERROR");
  });

  test("ML service unavailable returns 503 and timeout returns 504", async () => {
    mlClient.forwardCharacterizationRecompute.mockRejectedValueOnce(new MLServiceUnavailableError());
    let res = await request(app).post("/api/v1/characterization/recompute").send({ inputs: INPUTS });
    expect(res.status).toBe(503);
    mlClient.forwardCharacterizationRecompute.mockRejectedValueOnce(new MLServiceTimeoutError());
    res = await request(app).post("/api/v1/characterization/recompute").send({ inputs: INPUTS });
    expect(res.status).toBe(504);
  });
});
