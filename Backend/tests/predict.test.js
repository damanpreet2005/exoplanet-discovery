jest.mock("../src/services/mlClient");
const mlClient = require("../src/services/mlClient");
const request = require("supertest");
const { createApp } = require("../src/app");
const {
  MLServiceUnavailableError,
  MLServiceTimeoutError,
  UpstreamValidationError,
} = require("../src/errors");

const app = createApp();

const FAKE_ML_RESPONSE = {
  filename: "lightcurve.csv",
  diagnostics: { n_points_used: 3000, n_points_dropped: 0, baseline_days: 40, bls_period_days: 5 },
  extracted_features: { bls_period_days: 5.0 },
  prediction: 1,
  weighted_probability: 0.6,
  random_forest_probability: 0.55,
  cnn_probability: 0.65,
  weights: { random_forest: 0.5, cnn: 0.5 },
  model_version: "1.0",
  characterisation: { status: "computed", bls_period_days: 5.0 },
  physics_validation: { status: "not_implemented", message: "later" },
  warnings: ["best-effort"],
};

const LIGHT_CURVE_CSV = Buffer.from("time,flux\n0,1.0\n0.1,0.99\n0.2,1.0\n");

afterEach(() => jest.clearAllMocks());

test("valid light curve CSV alone is forwarded to the ML service and result returned", async () => {
  mlClient.forwardCsvPrediction.mockResolvedValue({ ...FAKE_ML_RESPONSE });

  const res = await request(app)
    .post("/api/v1/predict")
    .attach("file", LIGHT_CURVE_CSV, { filename: "lightcurve.csv", contentType: "text/csv" });

  expect(res.status).toBe(200);
  expect(res.body.filename).toBe("lightcurve.csv");
  expect(res.body.prediction).toBe(1);
  expect(res.body.request_id).toBeDefined();
  expect(mlClient.forwardCsvPrediction).toHaveBeenCalledWith(
    expect.objectContaining({ filename: "lightcurve.csv" })
  );
  // Nothing besides the file is forwarded.
  const callArgs = mlClient.forwardCsvPrediction.mock.calls[0][0];
  expect(callArgs.stellarParams).toBeUndefined();
});

test("request ID is generated and passed through to the ML client", async () => {
  mlClient.forwardCsvPrediction.mockResolvedValue({ ...FAKE_ML_RESPONSE });

  const res = await request(app)
    .post("/api/v1/predict")
    .set("X-Request-Id", "trace-99")
    .attach("file", LIGHT_CURVE_CSV, { filename: "lightcurve.csv", contentType: "text/csv" });

  expect(res.headers["x-request-id"]).toBe("trace-99");
  expect(res.body.request_id).toBe("trace-99");
  expect(mlClient.forwardCsvPrediction).toHaveBeenCalledWith(
    expect.objectContaining({ requestId: "trace-99" })
  );
});

test("missing file returns 422 without calling the ML service", async () => {
  const res = await request(app).post("/api/v1/predict");
  expect(res.status).toBe(422);
  expect(res.body.error.code).toBe("VALIDATION_ERROR");
  expect(mlClient.forwardCsvPrediction).not.toHaveBeenCalled();
});

test("empty file returns 422 without calling the ML service", async () => {
  const res = await request(app)
    .post("/api/v1/predict")
    .attach("file", Buffer.from(""), { filename: "empty.csv", contentType: "text/csv" });
  expect(res.status).toBe(422);
  expect(mlClient.forwardCsvPrediction).not.toHaveBeenCalled();
});

test("ML service unavailable returns 503", async () => {
  mlClient.forwardCsvPrediction.mockRejectedValue(new MLServiceUnavailableError());
  const res = await request(app)
    .post("/api/v1/predict")
    .attach("file", LIGHT_CURVE_CSV, { filename: "lightcurve.csv", contentType: "text/csv" });
  expect(res.status).toBe(503);
  expect(res.body.error.code).toBe("ML_SERVICE_UNAVAILABLE");
});

test("ML service timeout returns 504", async () => {
  mlClient.forwardCsvPrediction.mockRejectedValue(new MLServiceTimeoutError());
  const res = await request(app)
    .post("/api/v1/predict")
    .attach("file", LIGHT_CURVE_CSV, { filename: "lightcurve.csv", contentType: "text/csv" });
  expect(res.status).toBe(504);
  expect(res.body.error.code).toBe("ML_SERVICE_TIMEOUT");
});

test("ML service validation rejection is passed through as 422", async () => {
  mlClient.forwardCsvPrediction.mockRejectedValue(
    new UpstreamValidationError(422, { error: { code: "CSV_VALIDATION_ERROR", message: "bad csv" } })
  );
  const res = await request(app)
    .post("/api/v1/predict")
    .attach("file", LIGHT_CURVE_CSV, { filename: "lightcurve.csv", contentType: "text/csv" });
  expect(res.status).toBe(422);
  expect(res.body.error.code).toBe("CSV_VALIDATION_ERROR");
  expect(res.body.error.message).toBe("bad csv");
});

test("unexpected error returns structured 500 without leaking internals", async () => {
  mlClient.forwardCsvPrediction.mockRejectedValue(
    new Error("/secret/internal/path stack trace detail")
  );
  const res = await request(app)
    .post("/api/v1/predict")
    .attach("file", LIGHT_CURVE_CSV, { filename: "lightcurve.csv", contentType: "text/csv" });
  expect(res.status).toBe(500);
  expect(res.body.error.code).toBe("INTERNAL_ERROR");
  expect(JSON.stringify(res.body)).not.toContain("/secret/internal/path");
});

describe("POST /api/v1/predict/manual", () => {
  const FAKE_MANUAL_RESPONSE = {
    prediction: 1,
    weighted_probability: 0.72,
    random_forest_probability: 0.7,
    cnn_probability: 0.74,
    weights: { random_forest: 0.5, cnn: 0.5 },
    model_version: "1.0",
  };

  test("valid named parameters are forwarded to the ML service", async () => {
    mlClient.forwardNamedPrediction.mockResolvedValue({ ...FAKE_MANUAL_RESPONSE });

    const res = await request(app)
      .post("/api/v1/predict/manual")
      .send({ orbital_period: 384.84, transit_duration: 4.2 });

    expect(res.status).toBe(200);
    expect(res.body.prediction).toBe(1);
    expect(res.body.request_id).toBeDefined();
    expect(mlClient.forwardNamedPrediction).toHaveBeenCalledWith(
      { orbital_period: 384.84, transit_duration: 4.2 },
      expect.any(String)
    );
  });

  test("empty body returns 422 without calling the ML service", async () => {
    const res = await request(app).post("/api/v1/predict/manual").send({});
    expect(res.status).toBe(422);
    expect(res.body.error.code).toBe("VALIDATION_ERROR");
    expect(mlClient.forwardNamedPrediction).not.toHaveBeenCalled();
  });

  test("ML service missing-feature rejection is passed through as 422", async () => {
    mlClient.forwardNamedPrediction.mockRejectedValue(
      new UpstreamValidationError(422, { error: { code: "MISSING_FEATURE", message: "Missing required feature: koi_period." } })
    );
    const res = await request(app).post("/api/v1/predict/manual").send({ transit_duration: 4.2 });
    expect(res.status).toBe(422);
    expect(res.body.error.code).toBe("MISSING_FEATURE");
  });

  test("ML service unavailable returns 503", async () => {
    mlClient.forwardNamedPrediction.mockRejectedValue(new MLServiceUnavailableError());
    const res = await request(app).post("/api/v1/predict/manual").send({ orbital_period: 384.84 });
    expect(res.status).toBe(503);
    expect(res.body.error.code).toBe("ML_SERVICE_UNAVAILABLE");
  });
});

describe("GET /api/v1/feature-schema", () => {
  test("proxies the ML service's feature schema", async () => {
    const fakeSchema = { features: [{ canonical: "koi_period", display: "Orbital Period" }], order_configured: false };
    mlClient.fetchFeatureSchema.mockResolvedValue(fakeSchema);

    const res = await request(app).get("/api/v1/feature-schema");
    expect(res.status).toBe(200);
    expect(res.body).toEqual(fakeSchema);
  });

  test("ML service unavailable returns 503", async () => {
    mlClient.fetchFeatureSchema.mockRejectedValue(new MLServiceUnavailableError());
    const res = await request(app).get("/api/v1/feature-schema");
    expect(res.status).toBe(503);
  });
});
