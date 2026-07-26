# SPDX-License-Identifier: FSL-1.1-ALv2
"""Structured logging with contextvar correlation IDs and secret redaction.

Design: §7.2, §14.4 — stdlib logging + dictConfig + JSON formatter.
"""

from __future__ import annotations

import json
import logging
import logging.config
import re
import time
from contextvars import ContextVar
from typing import Any

# Context variables for request correlation
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
span_id_var: ContextVar[str] = ContextVar("span_id", default="")

# Patterns that must NEVER appear in logs (NFR-10, §14.4)
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
    re.compile(r"postgresql(?:\+\w+)?://[^\s]+"),
    re.compile(r"redis://[^\s]+"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9]{20,}"),
    re.compile(r"xai-[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN\s+(?:RSA\s+)?(?:PRIVATE|PUBLIC)\s+KEY-----"),
]

_REDACTED = "[REDACTED]"


def redact_secrets(text: str) -> str:
    """Scrub known secret patterns from a string."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(_REDACTED, text)
    return text


class SecretRedactingFilter(logging.Filter):
    """Scrubs secret patterns from log records before emission (§7.2, §14.4)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: redact_secrets(str(v)) if isinstance(v, str) else v for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(redact_secrets(a) if isinstance(a, str) else a for a in record.args)
        return True


class JSONFormatter(logging.Formatter):
    """Emits structured JSON log records with required correlation fields."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(""),
            "trace_id": trace_id_var.get(""),
            "span_id": span_id_var.get(""),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        # Include any extra fields
        if hasattr(record, "extra_fields"):
            log_entry.update(record.extra_fields)
        return json.dumps(log_entry, default=str)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z"


def configure_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """Configure stdlib logging with JSON formatter and secret redaction."""
    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "secret_redacting": {
                "()": SecretRedactingFilter,
            }
        },
        "formatters": {
            "json": {
                "()": JSONFormatter,
            },
            "console": {
                "format": "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": log_format if log_format in ("json", "console") else "json",
                "filters": ["secret_redacting"],
                "stream": "ext://sys.stdout",
            }
        },
        "root": {
            "level": log_level.upper(),
            "handlers": ["default"],
        },
    }
    logging.config.dictConfig(config)
