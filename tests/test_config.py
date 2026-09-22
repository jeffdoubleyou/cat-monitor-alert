from __future__ import annotations

import pytest
from pydantic import ValidationError

from cat_monitor.config import Settings


def test_loads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMERA_HOST", "10.0.0.8")
    monkeypatch.setenv("CAMERA_USER", "admin")
    monkeypatch.setenv("CAMERA_PASSWORD", "secret")
    monkeypatch.setenv("NTFY_TOPIC", "cats-in-the-yard")
    monkeypatch.setenv("DETECT_CLASSES", "cat, orange cat")
    settings = Settings(_env_file=None)
    assert settings.camera_host == "10.0.0.8"
    assert settings.snapshot_interval_seconds == 5.0
    assert settings.detect_class_list == ["cat", "orange cat"]
    assert settings.ntfy_url == "https://ntfy.sh/cats-in-the-yard"


def test_rejects_invalid_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DETECT_CONFIDENCE", "1.5")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_require_camera_and_ntfy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAMERA_HOST", raising=False)
    monkeypatch.delenv("CAMERA_RTSP_URL", raising=False)
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    settings = Settings(_env_file=None)
    with pytest.raises(ValueError, match="CAMERA_HOST"):
        settings.require_camera()
    with pytest.raises(ValueError, match="NTFY_TOPIC"):
        settings.require_ntfy()


def test_rtsp_override_skips_onvif_password_requirement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAMERA_RTSP_URL", "rtsp://10.0.0.8/stream")
    settings = Settings(_env_file=None)
    settings.require_camera()
