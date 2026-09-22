"""Helpers for RTSP/HTTP URLs that may contain camera credentials."""

from __future__ import annotations

from urllib.parse import quote, urlparse, urlunparse


def inject_credentials(uri: str, username: str, password: str) -> str:
    """Insert username/password into a URI when the camera omitted them."""
    parsed = urlparse(uri)
    if parsed.username or not username:
        return uri
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    user = quote(username, safe="")
    pw = quote(password, safe="")
    return urlunparse(parsed._replace(netloc=f"{user}:{pw}@{host}"))


def redact_url(uri: str) -> str:
    """Strip userinfo from a URL so it is safe to log."""
    parsed = urlparse(uri)
    if not parsed.username and not parsed.password:
        return uri
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=f"***:***@{host}"))
