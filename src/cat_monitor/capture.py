"""Grab a single JPEG frame from an RTSP URL."""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable

import cv2
import numpy as np

from cat_monitor.urls import redact_url

logger = logging.getLogger(__name__)


class CaptureError(RuntimeError):
    """Failed to decode a camera frame."""


def encode_jpeg(frame: np.ndarray, quality: int = 85) -> bytes:
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise CaptureError("Failed to encode JPEG")
    return buffer.tobytes()


def decode_image(data: bytes) -> np.ndarray:
    array = np.frombuffer(data, dtype=np.uint8)
    frame = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if frame is None:
        raise CaptureError("Failed to decode image bytes")
    return frame


class FrameGrabber:
    """Capture one recent frame, preferring ffmpeg over OpenCV's RTSP client."""

    def __init__(
        self,
        transport: str = "tcp",
        timeout_seconds: float = 15.0,
        run_command: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
        ffmpeg_path: str | None = None,
    ) -> None:
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self._run_command = run_command
        self._ffmpeg_path = ffmpeg_path if ffmpeg_path is not None else shutil.which("ffmpeg")

    def grab(self, rtsp_url: str) -> np.ndarray:
        errors: list[str] = []
        if self._ffmpeg_path:
            try:
                return self._grab_ffmpeg(rtsp_url)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"ffmpeg: {exc}")
                logger.warning("ffmpeg frame grab failed (%s): %s", redact_url(rtsp_url), exc)
        try:
            return self._grab_opencv(rtsp_url)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"opencv: {exc}")
            raise CaptureError(
                f"Could not grab a frame from {redact_url(rtsp_url)}: " + "; ".join(errors)
            ) from exc

    def _grab_ffmpeg(self, rtsp_url: str) -> np.ndarray:
        timeout_us = str(int(self.timeout_seconds * 1_000_000))
        result = self._run_command(
            [
                self._ffmpeg_path or "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-rtsp_transport",
                self.transport,
                "-timeout",
                timeout_us,
                "-i",
                rtsp_url,
                "-frames:v",
                "1",
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "pipe:1",
            ],
            capture_output=True,
            timeout=self.timeout_seconds + 5,
            check=False,
        )
        if result.returncode != 0 or not result.stdout:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            raise CaptureError(stderr or f"ffmpeg exited {result.returncode}")
        return decode_image(result.stdout)

    def _grab_opencv(self, rtsp_url: str) -> np.ndarray:
        capture = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        try:
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not capture.isOpened():
                raise CaptureError("OpenCV could not open the RTSP stream")
            ok, frame = capture.read()
            if not ok or frame is None:
                raise CaptureError("OpenCV opened the stream but returned no frame")
            return frame
        finally:
            capture.release()
