"""Centralized configuration for the ML inference service, sourced from environment variables."""
import os
from functools import lru_cache
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SERVICE_ROOT.parent


class Settings:
    app_env: str = os.getenv("APP_ENV", "development")

    # The model file lives in the repo-level `model/` directory, which is the
    # single authoritative location. Never allow this path to come from a request.
    model_path: str = os.getenv(
        "MODEL_PATH", str(REPO_ROOT / "model" / "hybrid_ensemble_model.pkl")
    )

    # Fusion weights. No pre-existing weighting scheme was found anywhere in the
    # repository (it was empty prior to this implementation), so both default to
    # an equal 0.5/0.5 split rather than an invented "scientifically meaningful"
    # split. Override via env vars if a real weighting scheme is decided later.
    rf_weight: float = float(os.getenv("RF_WEIGHT", "0.5"))
    cnn_weight: float = float(os.getenv("CNN_WEIGHT", "0.5"))

    model_version: str = os.getenv("MODEL_VERSION", "1.0")

    cache_ttl_seconds: int = int(os.getenv("CACHE_TTL", "300"))
    cache_max_size: int = int(os.getenv("CACHE_MAX_SIZE", "512"))

    csv_max_rows: int = int(os.getenv("CSV_MAX_ROWS", "1000"))
    csv_max_file_size_bytes: int = int(os.getenv("CSV_MAX_FILE_SIZE_BYTES", str(5 * 1024 * 1024)))

    # NASA Exoplanet Archive TAP (Table Access Protocol) sync endpoint --
    # the Archive's own supported programmatic interface, no API key
    # required. Configurable so a different mirror/environment can be
    # pointed at without a code change.
    nasa_api_base_url: str = os.getenv(
        "NASA_API_BASE_URL", "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
    )
    nasa_api_timeout_seconds: float = float(os.getenv("NASA_API_TIMEOUT_SECONDS", "8"))
    nasa_cache_ttl_seconds: int = int(os.getenv("NASA_CACHE_TTL_SECONDS", "3600"))
    nasa_cache_max_size: int = int(os.getenv("NASA_CACHE_MAX_SIZE", "512"))

    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    cors_allow_origins: list[str] = [
        o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()
    ]

    def validate(self) -> None:
        total = self.rf_weight + self.cnn_weight
        if self.rf_weight < 0 or self.cnn_weight < 0:
            raise ValueError("RF_WEIGHT and CNN_WEIGHT must be non-negative")
        if not (0.99 <= total <= 1.01):
            raise ValueError(
                f"RF_WEIGHT + CNN_WEIGHT must sum to 1.0 (got {total})"
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate()
    return settings
