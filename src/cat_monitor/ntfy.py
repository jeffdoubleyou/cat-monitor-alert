"""Publish cat alerts to ntfy."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from cat_monitor.detector import DetectionResult

logger = logging.getLogger(__name__)


class NtfyError(RuntimeError):
    """ntfy publish failed."""


def build_headers(
    *,
    title: str,
    message: str,
    priority: str,
    filename: str,
    token: str = "",
) -> dict[str, str]:
    headers = {
        "Title": title,
        "Message": message,
        "Priority": priority,
        "Tags": "cat,warning",
        "Filename": filename,
        "Content-Type": "image/jpeg",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class NtfyClient:
    def __init__(
        self,
        server: str,
        topic: str,
        *,
        token: str = "",
        title: str = "Cat detected",
        priority: str = "high",
        timeout: float = 15.0,
        session: requests.Session | None = None,
    ) -> None:
        self.server = server.rstrip("/")
        self.topic = topic
        self.token = token
        self.title = title
        self.priority = priority
        self.timeout = timeout
        self._session = session or requests.Session()

    @property
    def url(self) -> str:
        return f"{self.server}/{self.topic}"

    def send_alert(self, result: DetectionResult, image_jpeg: bytes) -> None:
        best = result.best
        confidence = f"{best.confidence:.0%}" if best else "unknown"
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        message = f"Cat detected ({confidence} confidence) at {timestamp}"
        filename = f"cat-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jpg"
        headers = build_headers(
            title=self.title,
            message=message,
            priority=self.priority,
            filename=filename,
            token=self.token,
        )
        response = self._session.put(
            self.url,
            data=image_jpeg,
            headers=headers,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise NtfyError(f"ntfy returned HTTP {response.status_code}: {response.text[:300]}")
        logger.info("Sent ntfy alert to %s", self.url)
