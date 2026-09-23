import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from cat_monitor.capture import CaptureError, FrameGrabber, decode_image, encode_jpeg


def _jpeg_bytes() -> bytes:
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    frame[:] = (12, 64, 200)
    return encode_jpeg(frame)


def test_roundtrip_jpeg() -> None:
    original = np.zeros((16, 16, 3), dtype=np.uint8)
    original[2:8, 2:8] = (0, 255, 0)
    decoded = decode_image(encode_jpeg(original))
    assert decoded.shape == original.shape


def test_ffmpeg_grab_decodes_file() -> None:
    jpeg = _jpeg_bytes()

    def runner(args, **kwargs):
        Path(args[-1]).write_bytes(jpeg)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"", stderr=b"")

    grabber = FrameGrabber(run_command=runner, ffmpeg_path="/usr/bin/ffmpeg")
    frame = grabber.grab("rtsp://camera/stream")
    assert frame.shape[2] == 3


def test_ffmpeg_error_skips_opencv_for_rtsp() -> None:
    runner = MagicMock(
        return_value=subprocess.CompletedProcess(
            args=["ffmpeg"],
            returncode=1,
            stdout=b"",
            stderr=b"rtsp://admin:secret@10.0.0.8/stream connection refused",
        )
    )
    grabber = FrameGrabber(run_command=runner, ffmpeg_path="/usr/bin/ffmpeg")
    with pytest.raises(CaptureError, match="Could not grab a frame") as exc:
        grabber.grab("rtsp://admin:secret@10.0.0.8/stream")
    assert "secret" not in str(exc.value)
    assert "opencv" not in str(exc.value).lower()
