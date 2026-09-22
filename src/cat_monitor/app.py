"""Main monitoring loop and CLI."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path

import cv2

from cat_monitor.camera import CameraError, OnvifCamera
from cat_monitor.capture import CaptureError, FrameGrabber, encode_jpeg
from cat_monitor.config import Settings
from cat_monitor.detector import CatDetector, DetectionResult
from cat_monitor.ntfy import NtfyClient
from cat_monitor.urls import inject_credentials, redact_url

logger = logging.getLogger(__name__)


class CatMonitor:
    """Grab frames on an interval, detect cats, then sound the camera and notify ntfy."""

    def __init__(
        self,
        settings: Settings,
        camera: OnvifCamera,
        grabber: FrameGrabber,
        detector: CatDetector,
        ntfy: NtfyClient,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.camera = camera
        self.grabber = grabber
        self.detector = detector
        self.ntfy = ntfy
        self.clock = clock
        self.sleeper = sleeper
        self._last_alert_at = 0.0
        self._rtsp_url: str | None = None

    def resolve_rtsp_url(self) -> str:
        if self.settings.camera_rtsp_url:
            url = inject_credentials(
                self.settings.camera_rtsp_url,
                self.settings.camera_user,
                self.settings.camera_password,
            )
        else:
            url = self.camera.get_rtsp_url()
        self._rtsp_url = url
        return url

    def tick(self) -> bool:
        """Run one capture/detect cycle. Returns True when an alert is sent."""
        if not self._rtsp_url:
            self.resolve_rtsp_url()
        assert self._rtsp_url is not None
        frame = self.grabber.grab(self._rtsp_url)
        result = self.detector.detect(frame)
        if not result.has_cat:
            logger.debug("No cat in frame")
            return False

        best = result.best
        logger.info(
            "Cat detected (%.0f%%)",
            (best.confidence * 100) if best else 0,
        )
        remaining = self.settings.alert_cooldown_seconds - (self.clock() - self._last_alert_at)
        if self._last_alert_at and remaining > 0:
            logger.info("Skipping alert; cooldown has %.1fs remaining", remaining)
            return False

        annotated = self.detector.annotate(frame, result)
        jpeg = encode_jpeg(annotated)
        self._maybe_save_snapshot(jpeg)
        self._dispatch_alert(result, jpeg)
        self._last_alert_at = self.clock()
        return True

    def run(self, once: bool = False) -> None:
        self.resolve_rtsp_url()
        logger.info(
            "Watching %s every %.1fs (cooldown %.1fs)",
            redact_url(self._rtsp_url or ""),
            self.settings.snapshot_interval_seconds,
            self.settings.alert_cooldown_seconds,
        )
        while True:
            started = self.clock()
            try:
                self.tick()
            except CaptureError:
                logger.exception("Frame capture failed")
                self._rtsp_url = None
            except Exception:  # noqa: BLE001
                logger.exception("Monitor cycle failed")
            if once:
                return
            elapsed = self.clock() - started
            delay = max(0.0, self.settings.snapshot_interval_seconds - elapsed)
            self.sleeper(delay)

    def process_image(self, image_path: Path) -> bool:
        frame = cv2.imread(str(image_path))
        if frame is None:
            raise CaptureError(f"Could not read image {image_path}")
        result = self.detector.detect(frame)
        if not result.has_cat:
            logger.info("No cat found in %s", image_path)
            return False
        annotated = self.detector.annotate(frame, result)
        jpeg = encode_jpeg(annotated)
        self._maybe_save_snapshot(jpeg)
        self._dispatch_alert(result, jpeg)
        return True

    def _dispatch_alert(self, result: DetectionResult, jpeg: bytes) -> None:
        if self.settings.dry_run:
            logger.info("Dry run: would play camera sound and send ntfy alert")
            return
        try:
            self.ntfy.send_alert(result, jpeg)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send ntfy alert")
        try:
            self.camera.play_sound()
        except CameraError:
            logger.exception("Failed to play camera sound")
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected error playing camera sound")

    def _maybe_save_snapshot(self, jpeg: bytes) -> None:
        if not self.settings.snapshot_dir:
            return
        directory = Path(self.settings.snapshot_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"cat-{int(time.time())}.jpg"
        path.write_bytes(jpeg)
        logger.info("Wrote snapshot %s", path)


def build_monitor(settings: Settings) -> CatMonitor:
    camera = OnvifCamera(
        host=settings.camera_host,
        port=settings.camera_onvif_port,
        username=settings.camera_user,
        password=settings.camera_password,
        use_https=settings.camera_onvif_https,
        timeout=settings.camera_onvif_timeout,
        profile_index=settings.camera_profile_index,
        audio_clip_token=settings.onvif_audio_clip_token,
        audio_repeat_cycles=settings.onvif_audio_repeat_cycles,
        audio_backchannel_url=settings.audio_backchannel_url,
        cgi_port=settings.camera_http_port,
        tapo_username=settings.tapo_username,
        tapo_password=settings.tapo_cloud_password,
        tapo_alarm_seconds=settings.tapo_alarm_seconds,
        tapo_alarm_sound=settings.tapo_alarm_sound,
    )
    grabber = FrameGrabber(
        transport=settings.rtsp_transport,
        timeout_seconds=settings.capture_timeout_seconds,
    )
    detector = CatDetector(
        model_path=settings.yolo_model,
        confidence=settings.detect_confidence,
        classes=settings.detect_class_list,
        device=settings.inference_device,
    )
    ntfy = NtfyClient(
        server=settings.ntfy_server,
        topic=settings.ntfy_topic,
        token=settings.ntfy_token,
        title=settings.ntfy_title,
        priority=settings.ntfy_priority,
    )
    return CatMonitor(settings, camera, grabber, detector, ntfy)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect cats on an ONVIF RTSP camera, play a sound, and alert via ntfy.",
    )
    parser.add_argument("--once", action="store_true", help="Grab and process a single frame, then exit")
    parser.add_argument("--image", type=Path, help="Run detection on a still image instead of the camera")
    parser.add_argument("--dry-run", action="store_true", help="Detect only; do not play sound or notify")
    parser.add_argument("--play-sound", action="store_true", help="Play the camera alert sound once and exit")
    parser.add_argument("--notify-test", action="store_true", help="Send a test ntfy alert and exit")
    return parser.parse_args(argv)


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = Settings()
    if args.dry_run:
        settings = settings.model_copy(update={"dry_run": True})
    configure_logging(settings.log_level)

    try:
        if args.notify_test:
            settings.require_ntfy()
        elif args.image is None:
            settings.require_camera()
            if not settings.dry_run and not args.play_sound:
                settings.require_ntfy()
        elif not settings.dry_run:
            settings.require_ntfy()
    except ValueError as exc:
        logger.error("%s", exc)
        return 2

    if args.notify_test:
        NtfyClient(
            server=settings.ntfy_server,
            topic=settings.ntfy_topic,
            token=settings.ntfy_token,
            title=settings.ntfy_title,
            priority=settings.ntfy_priority,
        ).send_test()
        return 0

    monitor = build_monitor(settings)
    try:
        if args.play_sound:
            monitor.camera.play_sound()
            return 0
        if args.image:
            if not args.image.exists():
                logger.error("Image not found: %s", args.image)
                return 1
            found = monitor.process_image(args.image)
            return 0 if found else 1
        monitor.run(once=args.once)
    except KeyboardInterrupt:
        logger.info("Stopped")
        return 0
    except CaptureError as exc:
        logger.error("%s", exc)
        return 1
    except CameraError as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
