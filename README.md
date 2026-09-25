# Exoplanet Discovery Platform

An AI-assisted platform for analysing a star's observational light curve and identifying whether it shows a potential exoplanet transit signal, built around an existing, unmodified Random Forest + 1D CNN ensemble model.

## Core Pipeline

**Light curve (time, flux) CSV → Box Least Squares transit search → 17 internal ML features → Random Forest + 1D CNN → weighted fusion → prediction → characterisation**

Users upload only a `time`/`flux` CSV for one candidate — nothing else. Users never enter the 17 model features manually, and no additional properties (stellar, planetary, or otherwise) are ever requested. The ML service derives all 17 features automatically from the light curve alone.

## Architecture

```
React Frontend (Vite)
        │  HTTP (light-curve CSV, multipart/form-data)
        ▼
Node.js + Express API Gateway   (Backend/)
        │  HTTP (forwards the CSV)
        ▼
Python FastAPI ML Service       (ml_service/)
        │
        ▼
 CSV validation → Box Least Squares transit search → 17 features
        │
  ┌─────┴─────┐
  ▼           ▼
Random     1D CNN
Forest    (PyTorch)
  └─────┬─────┘
        ▼
 Weighted Fusion
        │
        ▼
 Prediction + Characterisation
```

- The **React frontend** talks only to the Express gateway, never to the ML service directly.
- The **Express gateway** is a pure orchestrator: request validation, request IDs, timeouts, limited retries, structured errors, health/readiness. It contains no ML logic.
- The **FastAPI ML service** owns the model: it loads the existing `.pkl` once at startup, runs a real transit search on the light curve, generates the 17 features, runs both models, applies weighted fusion, and caches repeated inputs.

## Existing Model Artifact

`model/hybrid_ensemble_model.pkl` is treated as immutable — never retrained, replaced, or modified by any code in this repository. It is a Python dict with three keys, verified by direct inspection:

- `random_forest` — a scikit-learn `RandomForestClassifier` (100 trees, `max_depth=15`), 17 input features, binary classes `[0, 1]`.
- `scaler` — a fitted scikit-learn `RobustScaler` (17 features), applied via `.transform()` only, never re-fit.
- `cnn_state_dict` — a PyTorch `state_dict` (weights only; the original `nn.Module` source was not present in the repository). `ml_service/app/cnn_model.py` reconstructs the minimal architecture required to load these exact weights (2×Conv2d/BatchNorm2d blocks + 2 Linear layers), documented in that file's docstring along with the one architectural detail (pooling type) that could not be verified from the weights alone.
- Loaded by `ml_service/app/model_loader.py` (`ModelRegistry.load()`), once at process startup. Prediction is performed by `ml_service/app/predictor.py` (`predict()` / `predict_with_cache()`), which runs the Random Forest and CNN and applies the weighted fusion — this logic is untouched by every change described below.

## How the 17 Features Are Generated — and Why It's a Best-Effort Reconstruction

**No feature-engineering or light-curve-processing code has ever existed in this repository.** Neither the scaler nor the Random Forest have `feature_names_in_` set — the model was trained on a plain array, with no recoverable feature names or original preprocessing source. `ml_service/app/lightcurve_extraction.py` documents this in detail and computes 17 real, computable values **entirely from the uploaded time/flux light curve** — nothing here is a fabricated number, and no stellar, planetary, or catalog property is ever requested or assumed:

| # | Feature | How it's computed |
|---|---|---|
| 1 | `bls_period_days` | Real Box Least Squares transit search (`astropy.timeseries.BoxLeastSquares`) |
| 2 | `bls_duration_hours` | BLS transit search |
| 3 | `bls_depth_ppm` | BLS transit search |
| 4 | `transit_epoch` | BLS transit search |
| 5 | `num_transits_observed` | Derived: `floor(baseline_days / period)` |
| 6 | `transit_snr` | BLS transit search (`depth_snr`) |
| 7 | `baseline_days` | `max(time) − min(time)` |
| 8 | `flux_scatter_ppm` | Std of the median-normalized flux |
| 9 | `duration_over_period` | `duration / period` (dimensionless transit shape ratio) |
| 10 | `odd_even_depth_ratio` | Depth(even-numbered transits) / depth(odd-numbered transits) — a classic eclipsing-binary check |
| 11 | `secondary_eclipse_depth_ppm` | Flux dip at phase 0.5 (opposite the primary transit) |
| 12 | `ingress_egress_asymmetry_ppm` | First-half vs second-half flux asymmetry within the transit |
| 13 | `transit_residual_scatter_ppm` | Scatter of in-transit points around the fitted box depth |
| 14 | `flux_skewness` | Skewness of the normalized flux distribution |
| 15 | `flux_kurtosis` | Excess kurtosis of the normalized flux distribution |
| 16 | `median_cadence_days` | Median spacing between consecutive time samples |
| 17 | `point_to_point_scatter_ppm` | RMS of consecutive-point flux differences (high-frequency noise) |

Because none of this was verifiable against an original training pipeline, every prediction response includes an explicit `warnings` field saying so — this is exploratory, not scientifically validated, output. `characterisation` in the response is real, computed transit-vetting data (odd/even ratio, secondary eclipse depth, etc.) — it deliberately does **not** claim physical planet properties (radius, mass, temperature), since those would require stellar parameters this pipeline never asks for.

## Project Structure

```
exoplanet-discovery/
├── model/
│   └── hybrid_ensemble_model.pkl   # existing, immutable trained model
├── ml_service/                     # Python + FastAPI ML inference service
│   ├── app/
│   │   ├── main.py, config.py, schemas.py, errors.py, logging_config.py
│   │   ├── model_loader.py         # loads the .pkl once at startup
│   │   ├── cnn_model.py            # reconstructed CNN architecture
│   │   ├── preprocessing.py        # RobustScaler.transform() wrapper
│   │   ├── lightcurve_extraction.py  # time+flux -> BLS transit search -> 17 features
│   │   ├── predictor.py            # RF + CNN + weighted fusion
│   │   ├── cache.py                # in-process TTL cache
│   │   └── routers/{health,predict,predict_csv}.py
│   └── tests/                      # pytest, 39 tests
├── Backend/                        # Node.js + Express API gateway
│   ├── src/
│   │   ├── server.js, app.js, config.js, errors.js, logger.js
│   │   ├── middleware/{requestId,errorHandler}.js
│   │   ├── services/mlClient.js    # timeout + retry HTTP client to ml_service
│   │   └── routes/{health,predict}.js
│   └── tests/                      # jest + supertest, 12 tests
├── Frontend/                       # React (Vite) app
│   ├── src/
│   │   ├── App.jsx, main.jsx, index.css
│   │   ├── api/client.js           # calls the Express gateway only
│   │   ├── context/AnalysisContext.jsx
│   │   ├── components/             # Sidebar, Starfield, CsvDropzone, ...
│   │   └── pages/                  # Upload, Results, PhysicsValidation, Characterisation, Status
│   └── tests/                      # vitest + testing-library, 6 tests
├── docker-compose.yml
└── .gitignore
```

## Technology Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 (Vite), react-router-dom, react-dropzone |
| Main Backend | Node.js 20 + Express |
| ML Service | Python 3 + FastAPI |
| Transit Search | astropy `BoxLeastSquares` |
| ML Models | scikit-learn `RandomForestClassifier`, PyTorch CNN (existing, pre-trained) |
| Communication | HTTP / multipart form-data |
| API Documentation | OpenAPI / Swagger (FastAPI `/docs`) |
| Deployment | Dockerfiles per service + `docker-compose.yml` |

## API

### Node.js + Express Gateway (public API, versioned)

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/predict` | Upload a light-curve CSV (`multipart/form-data`, field `file` — nothing else) and receive one prediction |
| `GET /api/v1/health` | Gateway liveness |
| `GET /api/v1/ready` | Gateway readiness, including ML service dependency status |

### FastAPI ML Service (internal — called only by the gateway)

| Endpoint | Purpose |
|---|---|
| `POST /predict/csv` | Light-curve CSV → BLS transit search → 17 features → RF + CNN → weighted fusion |
| `POST /predict` | Single prediction from 17 raw features by name — used internally/for testing |
| `GET /health` | Liveness |
| `GET /ready` | Readiness (model loaded) |
| `GET /docs`, `/redoc`, `/openapi.json` | Auto-generated API documentation |

### Request (`POST /api/v1/predict`)

`multipart/form-data` with a single field: `file` — CSV with `time` and `flux` columns (case-insensitive; extra columns ignored). No other fields are read or required.

### Response

```json
{
  "filename": "kepler_001.csv",
  "diagnostics": {
    "n_points_used": 4000, "n_points_dropped": 0, "baseline_days": 60.0,
    "bls_period_days": 6.2037, "bls_duration_hours": 2.4, "bls_depth_ppm": 7187.3,
    "bls_transit_snr": 0.06, "num_transits_observed": 9
  },
  "extracted_features": { "bls_period_days": 6.2037, "...": "..." },
  "prediction": 1,
  "weighted_probability": 0.855,
  "random_forest_probability": 0.71,
  "cnn_probability": 1.0,
  "weights": { "random_forest": 0.5, "cnn": 0.5 },
  "model_version": "1.0",
  "request_id": "…",
  "cache_hit": false,
  "characterisation": {
    "status": "computed",
    "bls_period_days": 6.2037, "bls_duration_hours": 2.4, "bls_depth_ppm": 7187.3,
    "bls_transit_snr": 0.06, "num_transits_observed": 9,
    "odd_even_depth_ratio": 1.11, "secondary_eclipse_depth_ppm": 18.2
  },
  "physics_validation": { "status": "not_implemented", "message": "Physics validation module — coming in a future implementation stage." },
  "warnings": ["The 17 model features were derived ... treat this prediction as exploratory, not scientifically validated."]
}
```

## Running Locally

Three services, three terminals.

**1. ML service (port 8001)**
```bash
cd ml_service
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

**2. Backend gateway (port 8000)**
```bash
cd Backend
npm install
ML_SERVICE_URL=http://127.0.0.1:8001 npm start
```

**3. Frontend (port 5173)**
```bash
cd Frontend
npm install
npm run dev
```
Open `http://localhost:5173` (use `localhost`, not `127.0.0.1` — Vite's dev server binds to IPv6 localhost only).

Or with Docker Compose (untested in the development environment used to build this — no Docker daemon was available there):
```bash
docker compose up --build
```

## Environment Variables

`ml_service/.env.example`: `MODEL_PATH`, `RF_WEIGHT`, `CNN_WEIGHT`, `MODEL_VERSION`, `CACHE_TTL`, `CACHE_MAX_SIZE`, `CSV_MAX_FILE_SIZE_BYTES`, `LOG_LEVEL`, `CORS_ALLOW_ORIGINS`

`Backend/.env.example`: `PORT`, `ML_SERVICE_URL`, `ML_SERVICE_TIMEOUT`, `ML_SERVICE_MAX_RETRIES`, `ML_SERVICE_RETRY_BACKOFF_SECONDS`, `CSV_MAX_FILE_SIZE_BYTES`, `LOG_LEVEL`, `CORS_ALLOW_ORIGINS`

`Frontend/.env.example`: `VITE_API_BASE_URL`

## Testing

| Suite | Command | Result |
|---|---|---|
| ML service (pytest) | `cd ml_service && pytest` | 39 passed |
| Backend gateway (jest) | `cd Backend && npm test` | 12 passed |
| Frontend (vitest) | `cd Frontend && npm test` | 6 passed |

Covers: valid/invalid/empty/malformed light-curve CSVs, missing `time`/`flux` columns, too few data points, a synthetic light curve with a known injected transit (verifies BLS recovers the injected period, and that the odd/even depth ratio stays near 1.0 with no spurious secondary eclipse for a genuine planet-like signal), model loading, RobustScaler math, RF/CNN weighted fusion math, cache hit/miss, ML-service-unavailable, timeout, retry-then-succeed, 4xx-not-retried, and structured error responses that don't leak internals.

Verified live (real running services, real `.pkl`, not mocked): a synthetic 60-day light curve with an injected 6.2-day transit, pushed through the real Express gateway and real FastAPI ML service using **only** a `time,flux` CSV, recovered a period of 6.2037 days.

## Current Implementation Status

| Component | Status |
|---|---|
| Existing trained model (RF + CNN + scaler) | ✅ used as-is, unmodified |
| Light-curve (time+flux only) CSV upload & validation | ✅ no additional inputs required |
| Box Least Squares transit search | ✅ real transit search (astropy), verified against a synthetic injected signal |
| Automatic 17-feature generation | ✅ best-effort reconstruction, purely from the light curve — see feature table above; not verified against original training pipeline |
| Random Forest inference | ✅ |
| 1D CNN inference | ✅ (reconstructed architecture — see model artifact section) |
| Weighted fusion | ✅ (weights configurable, default 0.5/0.5 — no prior weighting existed in the repo) |
| Node.js + Express gateway | ✅ |
| React frontend | ✅ |
| Caching, request IDs, timeouts, retries, health/ready, structured errors | ✅ |
| Characterisation (transit vetting: odd/even ratio, secondary eclipse) | ✅ real computed diagnostics |
| Physics validation | 🔭 Not implemented — explicit "not_implemented" status in the API and UI |

## Team

| Name | Programme | Batch |
|---|---|---|
| Bhavya Sabharwal | Information Technology | 2027 |
| Damanpreet Singh | Information Technology | 2027 |
| Harshita Gupta | Information Technology | 2027 |
