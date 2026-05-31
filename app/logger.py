"""
Structured Logger
-----------------
Emits JSON logs consumable by CloudWatch Logs Insights, Datadog, etc.
Every log line is a valid JSON object for easy querying.
"""

import json
import logging
import time
from datetime import datetime


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra"):
            log_data.update(record.extra)
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def log_request(
    logger: logging.Logger,
    api_key: str,
    endpoint: str,
    method: str,
    status_code: int,
    latency_ms: float,
    cache_hit: bool,
    rate_limited: bool,
    client_ip: str = "",
) -> None:
    """Emit a structured request log line."""
    level = logging.WARNING if rate_limited else (
        logging.ERROR if status_code >= 500 else logging.INFO
    )
    extra = {
        "api_key": api_key,
        "endpoint": endpoint,
        "method": method,
        "status_code": status_code,
        "latency_ms": round(latency_ms, 2),
        "cache_hit": cache_hit,
        "rate_limited": rate_limited,
        "client_ip": client_ip,
        "event": "api_request",
    }
    record = logging.LogRecord(
        name=logger.name,
        level=level,
        pathname="",
        lineno=0,
        msg="API request",
        args=(),
        exc_info=None,
    )
    record.extra = extra
    logger.handle(record)
