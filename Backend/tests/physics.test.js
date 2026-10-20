jest.mock("../src/services/mlClient");
const mlClient = require("../src/services/mlClient");
const request = require("supertest");
const { createApp } = require("../src/app");
const { MLServiceUnavailableError, MLServiceTimeoutError, UpstreamValidationError } = require("../src/errors");

const app = createApp();

const FAKE_PHYSICS_RESPONSE = {
  object_id: "KIC 11904151",
  overall_status: "PASS",
  summary: { tests_passed: 3, tests_review_required: 0, tests_not_evaluated: 0, message: "3 of 3 test(s) passed, 0 require investigation, 0 could not be evaluated." },
  tests: [],
  issues: [],
  recommendations: [],
  generated_at: "2026-01-01T00:00:00+00:00",
};

afterEach(() => jest.clearAllMocks());

describe("POST /api/v1/physics-validation", () => {
  test("valid named parameters are forwarded to the ML service", async () => {
    mlClient.forwardPhysicsValidation.mockResolvedValue({ ...FAKE_PHYSICS_RESPONSE });

    const res = await request(app)
      .post("/api/v1/physics-validation")
      .send({ koi_period: 9.48, koi_depth: 615.8 });

    expect(res.status).toBe(200);
    expect(res.body.overall_status).toBe("PASS");
    expect(res.body.request_id).toBeDefined();
    expect(mlClient.forwardPhysicsValidation).toHaveBeenCalledWith(
      { koi_period: 9.48, koi_depth: 615.8 },
      expect.any(String)
    );
  });

  test("empty body returns 422 without calling the ML service", async () => {
    const res = await request(app).post("/api/v1/physics-validation").send({});
    expect(res.status).toBe(422);
    expect(res.body.error.code).toBe("VALIDATION_ERROR");
    expect(mlClient.forwardPhysicsValidation).not.toHaveBeenCalled();
  });

  test("request ID is generated and echoed back", async () => {
    mlClient.forwardPhysicsValidation.mockResolvedValue({ ...FAKE_PHYSICS_RESPONSE });
    const res = await request(app)
      .post("/api/v1/physics-validation")
      .set("X-Request-Id", "trace-7")
      .send({ koi_period: 9.48 });

    expect(res.headers["x-request-id"]).toBe("trace-7");
    expect(res.body.request_id).toBe("trace-7");
    expect(mlClient.forwardPhysicsValidation).toHaveBeenCalledWith({ koi_period: 9.48 }, "trace-7");
  });

  test("ML service unavailable returns 503", async () => {
    mlClient.forwardPhysicsValidation.mockRejectedValue(new MLServiceUnavailableError());
    const res = await request(app).post("/api/v1/physics-validation").send({ koi_period: 9.48 });
    expect(res.status).toBe(503);
    expect(res.body.error.code).toBe("ML_SERVICE_UNAVAILABLE");
  });

  test("ML service timeout returns 504", async () => {
    mlClient.forwardPhysicsValidation.mockRejectedValue(new MLServiceTimeoutError());
    const res = await request(app).post("/api/v1/physics-validation").send({ koi_period: 9.48 });
    expect(res.status).toBe(504);
    expect(res.body.error.code).toBe("ML_SERVICE_TIMEOUT");
  });

  test("upstream validation rejection is passed through", async () => {
    mlClient.forwardPhysicsValidation.mockRejectedValue(
      new UpstreamValidationError(422, { error: { code: "VALIDATION_ERROR", message: "bad input" } })
    );
    const res = await request(app).post("/api/v1/physics-validation").send({ koi_period: 9.48 });
    expect(res.status).toBe(422);
    expect(res.body.error.message).toBe("bad input");
  });
});
