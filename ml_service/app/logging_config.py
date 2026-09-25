"""Structured (JSON) logging configuration for the ML service."""
import logging
import sys
import json
import time


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "endpoint", "duration_ms", "inference_ms",
                    "model_version", "cache_hit", "status_code"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger("ml_service")
    root.setLevel(level)
    root.handlers = [handler]
    root.propagate = False

    access = logging.getLogger("uvicorn.access")
    access.handlers = [handler]
