import subprocess
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


def test_ffmpeg_grab_decodes_stdout() -> None:
    jpeg = _jpeg_bytes()
    runner = MagicMock(
        return_value=subprocess.CompletedProcess(
            args=["ffmpeg"],
            returncode=0,
            stdout=jpeg,
            stderr=b"",
        )
    )
    grabber = FrameGrabber(run_command=runner, ffmpeg_path="/usr/bin/ffmpeg")
    frame = grabber.grab("rtsp://camera/stream")
    assert frame.shape[2] == 3
    runner.assert_called_once()
    command = runner.call_args.args[0]
    assert command[0] == "/usr/bin/ffmpeg"
    assert "rtsp://camera/stream" in command


def test_ffmpeg_error_falls_back_then_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = MagicMock(
        return_value=subprocess.CompletedProcess(
            args=["ffmpeg"],
            returncode=1,
            stdout=b"",
            stderr=b"connection refused",
        )
    )
    grabber = FrameGrabber(run_command=runner, ffmpeg_path="/usr/bin/ffmpeg")
    monkeypatch.setattr(grabber, "_grab_opencv", lambda url: (_ for _ in ()).throw(CaptureError("nope")))
    with pytest.raises(CaptureError, match="Could not grab a frame"):
        grabber.grab("rtsp://camera/stream")
