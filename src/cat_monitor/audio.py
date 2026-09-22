"""Generate a short alarm tone for camera talk-back."""

from __future__ import annotations

import math
import wave
from pathlib import Path

# ITU-T G.711 A-law segment ends (14-bit linear magnitudes).
_SEG_END = (0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF, 0x3FFF, 0x7FFF)


def _search(value: int) -> int:
    for index, limit in enumerate(_SEG_END):
        if value <= limit:
            return index
    return len(_SEG_END)


def _linear_to_alaw(sample: int) -> int:
    """Encode one 16-bit PCM sample as an A-law byte."""
    pcm = sample
    if pcm >= 0:
        mask = 0xD5
    else:
        mask = 0x55
        pcm = -pcm - 8
    if pcm > 32635:
        pcm = 32635
    segment = _search(pcm)
    if segment >= 8:
        return 0x7F ^ mask
    aval = segment << 4
    if segment < 2:
        aval |= (pcm >> 4) & 0x0F
    else:
        aval |= (pcm >> (segment + 3)) & 0x0F
    return aval ^ mask


def pcm16le_to_alaw(pcm: bytes) -> bytes:
    try:
        import audioop

        return audioop.lin2alaw(pcm, 2)
    except Exception:
        encoded = bytearray()
        for index in range(0, len(pcm) - 1, 2):
            sample = int.from_bytes(pcm[index : index + 2], "little", signed=True)
            encoded.append(_linear_to_alaw(sample))
        return bytes(encoded)


def alert_pcm16le(sample_rate: int = 8000, duration_seconds: float = 1.2) -> bytes:
    """Return a 16-bit little-endian mono alarm chirp."""
    sample_count = int(sample_rate * duration_seconds)
    frames = bytearray()
    for index in range(sample_count):
        time_s = index / sample_rate
        frequency = 880 + 440 * math.sin(2 * math.pi * 6 * time_s)
        envelope = min(1.0, time_s * 12) * min(1.0, (duration_seconds - time_s) * 8)
        sample = int(max(-1.0, min(1.0, envelope * math.sin(2 * math.pi * frequency * time_s))) * 28000)
        frames.extend(sample.to_bytes(2, "little", signed=True))
    return bytes(frames)


def alert_alaw_bytes(sample_rate: int = 8000, duration_seconds: float = 1.2) -> bytes:
    """Return G.711 A-law bytes for Amcrest/Dahua CGI talk-back."""
    return pcm16le_to_alaw(alert_pcm16le(sample_rate, duration_seconds))


def write_alert_wav(path: Path, sample_rate: int = 8000, duration_seconds: float = 1.2) -> None:
    """Write an 8 kHz mono 16-bit WAV alarm chirp to ``path``."""
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(alert_pcm16le(sample_rate, duration_seconds))
