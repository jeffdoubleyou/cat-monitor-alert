from pathlib import Path
from unittest.mock import patch

from cat_monitor.app import CatMonitor, parse_args
from cat_monitor.config import Settings
from cat_monitor.detector import Detection, DetectionResult


class FakeGrabber:
    def __init__(self) -> None:
        self.calls = 0

    def grab(self, url: str):
        self.calls += 1
        return {"url": url}


class FakeDetector:
    def __init__(self, result: DetectionResult) -> None:
        self.result = result

    def detect(self, frame):
        return self.result

    def annotate(self, frame, result):
        return frame


class FakeCamera:
    def __init__(self) -> None:
        self.sounds = 0
        self.rtsp_lookups = 0

    def get_rtsp_url(self) -> str:
        self.rtsp_lookups += 1
        return "rtsp://admin:secret@10.0.0.8/stream"

    def play_sound(self) -> None:
        self.sounds += 1


class FakeNtfy:
    def __init__(self) -> None:
        self.alerts: list[tuple] = []

    def send_alert(self, result, jpeg):
        self.alerts.append((result, jpeg))


def _settings(**overrides) -> Settings:
    data = {
        "camera_host": "10.0.0.8",
        "camera_user": "admin",
        "camera_password": "secret",
        "ntfy_topic": "cats",
        "alert_cooldown_seconds": 30,
        "snapshot_interval_seconds": 5,
    }
    data.update(overrides)
    return Settings(_env_file=None, **data)


def _monitor(result: DetectionResult, settings: Settings | None = None) -> tuple[CatMonitor, FakeCamera, FakeNtfy, FakeGrabber]:
    camera = FakeCamera()
    ntfy = FakeNtfy()
    grabber = FakeGrabber()
    monitor = CatMonitor(
        settings or _settings(),
        camera,  # type: ignore[arg-type]
        grabber,  # type: ignore[arg-type]
        FakeDetector(result),  # type: ignore[arg-type]
        ntfy,  # type: ignore[arg-type]
        clock=lambda: 100.0,
        sleeper=lambda _delay: None,
    )
    return monitor, camera, ntfy, grabber


def test_tick_alerts_on_cat() -> None:
    result = DetectionResult((Detection("cat", 0.9, (0, 0, 10, 10)),))
    monitor, camera, ntfy, grabber = _monitor(result)
    with patch("cat_monitor.app.encode_jpeg", return_value=b"jpeg"):
        assert monitor.tick() is True
    assert grabber.calls == 1
    assert camera.sounds == 1
    assert ntfy.alerts == [(result, b"jpeg")]


def test_tick_respects_cooldown() -> None:
    result = DetectionResult((Detection("cat", 0.9, (0, 0, 10, 10)),))
    times = iter([100.0, 100.0, 110.0, 110.0])
    monitor, camera, ntfy, _grabber = _monitor(result)
    monitor.clock = lambda: next(times)
    with patch("cat_monitor.app.encode_jpeg", return_value=b"jpeg"):
        assert monitor.tick() is True
        assert monitor.tick() is False
    assert camera.sounds == 1
    assert len(ntfy.alerts) == 1


def test_tick_ignores_empty_frames() -> None:
    monitor, camera, ntfy, _grabber = _monitor(DetectionResult())
    assert monitor.tick() is False
    assert camera.sounds == 0
    assert ntfy.alerts == []


def test_dry_run_skips_side_effects() -> None:
    result = DetectionResult((Detection("cat", 0.9, (0, 0, 10, 10)),))
    monitor, camera, ntfy, _grabber = _monitor(result, _settings(dry_run=True))
    with patch("cat_monitor.app.encode_jpeg", return_value=b"jpeg"):
        assert monitor.tick() is True
    assert camera.sounds == 0
    assert ntfy.alerts == []


def test_run_once_uses_explicit_rtsp_url() -> None:
    result = DetectionResult()
    monitor, camera, _ntfy, grabber = _monitor(
        result,
        _settings(camera_rtsp_url="rtsp://10.0.0.8/sub"),
    )
    monitor.run(once=True)
    assert camera.rtsp_lookups == 0
    assert grabber.calls == 1


def test_parse_args() -> None:
    args = parse_args(["--once", "--dry-run", "--image", "cat.jpg"])
    assert args.once is True
    assert args.dry_run is True
    assert args.image == Path("cat.jpg")
