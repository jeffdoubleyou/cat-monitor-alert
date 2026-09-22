import wave
from pathlib import Path

from cat_monitor.audio import write_alert_wav


def test_writes_mono_wav(tmp_path: Path) -> None:
    path = tmp_path / "alert.wav"
    write_alert_wav(path, duration_seconds=0.2)
    with wave.open(str(path), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 8000
        assert wav_file.getnframes() > 0


def test_alert_alaw_is_8khz() -> None:
    from cat_monitor.audio import alert_alaw_bytes

    payload = alert_alaw_bytes(duration_seconds=0.25)
    assert len(payload) == 2000
    assert payload != b"\x00" * len(payload)
