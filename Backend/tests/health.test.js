jest.mock("../src/services/mlClient");
const mlClient = require("../src/services/mlClient");
const request = require("supertest");
const { createApp } = require("../src/app");

const app = createApp();

afterEach(() => jest.clearAllMocks());

test("GET /api/v1/health returns alive", async () => {
  const res = await request(app).get("/api/v1/health");
  expect(res.status).toBe(200);
  expect(res.body.status).toBe("alive");
});

test("GET /api/v1/ready reports ml_service ready", async () => {
  mlClient.checkReady.mockResolvedValue(true);
  const res = await request(app).get("/api/v1/ready");
  expect(res.status).toBe(200);
  expect(res.body.dependencies.ml_service).toBe("ready");
});

test("GET /api/v1/ready reports ml_service unavailable without failing the gateway", async () => {
  mlClient.checkReady.mockResolvedValue(false);
  const res = await request(app).get("/api/v1/ready");
  expect(res.status).toBe(200);
  expect(res.body.dependencies.ml_service).toBe("unavailable");
});

test("unknown route returns structured 404", async () => {
  const res = await request(app).get("/api/v1/does-not-exist");
  expect(res.status).toBe(404);
  expect(res.body.error.code).toBe("NOT_FOUND");
});
