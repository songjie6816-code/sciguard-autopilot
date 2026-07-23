"""Recursive local redaction before any text can reach an LLM provider."""

from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel

REDACTED = {
    "secret": "[REDACTED_SECRET]",
    "email": "[REDACTED_EMAIL]",
    "internal_url": "[REDACTED_INTERNAL_URL]",
    "raw_rows": "[RAW_ROWS_OMITTED]",
}

_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)
_API_TOKEN = re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{8,}\b")
_URL = re.compile(r"https?://[^\s<>\"']+")
_SECRET_KEYS = {
    "api_key", "apikey", "authorization", "password", "passwd", "secret", "token",
    "access_token", "refresh_token", "client_secret", "llm_api_key", "datahub_token",
}
_RAW_ROW_KEYS = {"rows", "records", "raw_rows", "raw_data", "samples", "dataframe"}


class RedactionResult(BaseModel):
    value: Any
    counts: dict[str, int]
    raw_rows_removed: int = 0

    @property
    def total_redactions(self) -> int:
        return sum(self.counts.values())


def _is_internal_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
        if host in {"localhost", "host.docker.internal"}:
            return True
        if host.endswith((".local", ".internal", ".localhost")):
            return True
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def contains_internal_url(value: str) -> bool:
    return any(_is_internal_url(match.group(0)) for match in _URL.finditer(value))


class Redactor:
    def redact(self, value: Any) -> RedactionResult:
        counts = {"secret": 0, "email": 0, "internal_url": 0, "raw_rows": 0}
        raw_rows_removed = 0

        def walk(item: Any, key: str | None = None) -> Any:
            nonlocal raw_rows_removed
            normalized = (key or "").lower().replace("-", "_")
            if normalized in _RAW_ROW_KEYS:
                counts["raw_rows"] += 1
                raw_rows_removed += len(item) if isinstance(item, list) else 1
                return REDACTED["raw_rows"]
            if normalized in _SECRET_KEYS or normalized.endswith(("_token", "_secret", "_password")):
                counts["secret"] += 1
                return REDACTED["secret"]
            if isinstance(item, dict):
                return {str(k): walk(v, str(k)) for k, v in item.items()}
            if isinstance(item, (list, tuple)):
                return [walk(child) for child in item]
            if not isinstance(item, str):
                return item

            def internal_url(match: re.Match[str]) -> str:
                if _is_internal_url(match.group(0)):
                    counts["internal_url"] += 1
                    return REDACTED["internal_url"]
                return match.group(0)

            text, n = _BEARER.subn(REDACTED["secret"], item)
            counts["secret"] += n
            text, n = _API_TOKEN.subn(REDACTED["secret"], text)
            counts["secret"] += n
            text, n = _EMAIL.subn(REDACTED["email"], text)
            counts["email"] += n
            return _URL.sub(internal_url, text)

        return RedactionResult(
            value=walk(value), counts=counts, raw_rows_removed=raw_rows_removed
        )
