"""ONVIF camera access: RTSP discovery and speaker playback."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cat_monitor.audio import alert_alaw_bytes, write_alert_wav
from cat_monitor.urls import inject_credentials, redact_url

logger = logging.getLogger(__name__)


class CameraError(RuntimeError):
    """Camera / ONVIF operation failed."""


def _get(obj: Any, *names: str) -> Any:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def extract_clip_tokens(clips: Any) -> list[str]:
    """Pull audio-clip tokens out of the various ONVIF response shapes."""
    if clips is None:
        return []
    items = clips
    if isinstance(clips, dict):
        items = clips.get("AudioClip") or clips.get("AudioClips") or clips.get("Configuration") or clips
    else:
        nested = _get(clips, "AudioClip", "AudioClips", "Configuration")
        if nested is not None:
            items = nested
    tokens: list[str] = []
    for item in _as_list(items):
        token = _get(item, "token", "Token")
        if token:
            tokens.append(str(token))
    return tokens


class OnvifCamera:
    """Thin wrapper around an ONVIF client for stream URIs and audio clips."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        use_https: bool = False,
        timeout: int = 10,
        profile_index: int = 0,
        audio_clip_token: str = "",
        audio_repeat_cycles: int = 1,
        audio_backchannel_url: str = "",
        client_factory: Callable[..., Any] | None = None,
        run_command: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
        http_post: Callable[..., Any] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_https = use_https
        self.timeout = timeout
        self.profile_index = profile_index
        self.audio_clip_token = audio_clip_token
        self.audio_repeat_cycles = audio_repeat_cycles
        self.audio_backchannel_url = audio_backchannel_url
        self._client_factory = client_factory
        self._run_command = run_command
        self._http_post = http_post
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            factory = self._client_factory
            if factory is None:
                from onvif import ONVIFClient

                factory = ONVIFClient
            self._client = factory(
                self.host,
                self.port,
                self.username,
                self.password,
                timeout=self.timeout,
                use_https=self.use_https,
                verify_ssl=False,
            )
        return self._client

    def get_rtsp_url(self) -> str:
        """Ask the camera for an RTSP URI and inject credentials if needed."""
        client = self._get_client()
        uri = self._stream_uri_from_media(client) or self._stream_uri_from_media2(client)
        if not uri:
            raise CameraError("Camera did not return an RTSP stream URI")
        credentialed = inject_credentials(uri, self.username, self.password)
        logger.info("Resolved RTSP URI %s", redact_url(credentialed))
        return credentialed

    def play_sound(self) -> None:
        """Play a warning sound on the camera speaker."""
        errors: list[str] = []
        try:
            self._play_audio_clip()
            logger.info("Played ONVIF audio clip on camera")
            return
        except Exception as exc:  # noqa: BLE001 - camera firmware varies widely
            errors.append(f"ONVIF audio clip: {exc}")
            logger.warning("ONVIF PlayAudioClip failed: %s", exc)
            self._client = None

        try:
            self._play_cgi_audio()
            logger.info("Played alert tone via camera CGI talk-back")
            return
        except Exception as exc:  # noqa: BLE001
            errors.append(f"CGI talk-back: {exc}")
            logger.warning("CGI talk-back failed: %s", exc)

        if self.audio_backchannel_url:
            try:
                self._play_backchannel()
                logger.info("Played alert tone via RTSP backchannel")
                return
            except Exception as exc:  # noqa: BLE001
                errors.append(f"RTSP backchannel: {exc}")
                logger.warning("RTSP backchannel playback failed: %s", exc)

        raise CameraError("Could not play a sound on the camera: " + "; ".join(errors))

    def _stream_uri_from_media(self, client: Any) -> str | None:
        try:
            media = client.media()
            profiles = _as_list(media.GetProfiles())
            profile = profiles[self.profile_index]
            token = _get(profile, "token", "Token")
            stream = media.GetStreamUri(
                ProfileToken=token,
                StreamSetup={"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}},
            )
            return str(_get(stream, "Uri", "uri"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Media GetStreamUri failed: %s", exc)
            return None

    def _stream_uri_from_media2(self, client: Any) -> str | None:
        try:
            media2 = client.media2()
            profiles = _as_list(media2.GetProfiles())
            profile = profiles[self.profile_index]
            token = _get(profile, "token", "Token")
            stream = media2.GetStreamUri(Protocol="RTSP", ProfileToken=token)
            return str(_get(stream, "Uri", "uri"))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Media2 GetStreamUri failed: %s", exc)
            return None

    def _play_audio_clip(self) -> None:
        client = self._get_client()
        media2 = client.media2()
        token = self.audio_clip_token
        if not token:
            tokens = extract_clip_tokens(media2.GetAudioClips())
            if not tokens:
                raise CameraError("Camera has no ONVIF audio clips configured")
            token = tokens[0]
            logger.info("Using camera audio clip token %s", token)
        media2.PlayAudioClip(
            Token=token,
            Play=True,
            RepeatCycles=self.audio_repeat_cycles,
        )

    def _play_cgi_audio(self) -> None:
        """Amcrest/Dahua HTTP CGI talk-back (G.711 A-law)."""
        import requests
        from requests.auth import HTTPDigestAuth

        scheme = "https" if self.use_https else "http"
        url = (
            f"{scheme}://{self.host}:{self.port}"
            "/cgi-bin/audio.cgi?action=postAudio&httptype=singlepart&channel=1"
        )
        alaw = alert_alaw_bytes()
        poster = self._http_post or requests.post
        try:
            response = poster(
                url,
                files={"file": ("alert.al", alaw, "Audio/G.711A")},
                auth=HTTPDigestAuth(self.username, self.password),
                headers={"Content-Type": "Audio/G.711A", "Content-Length": "9999999"},
                timeout=self.timeout,
            )
        except requests.exceptions.ReadTimeout:
            # These cameras often keep the POST open after playing the tone.
            return
        if getattr(response, "status_code", 200) >= 400:
            body = getattr(response, "text", "")[:200]
            raise CameraError(f"CGI postAudio HTTP {response.status_code}: {body}")

    def _play_backchannel(self) -> None:
        url = inject_credentials(self.audio_backchannel_url, self.username, self.password)
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "alert.wav"
            write_alert_wav(wav_path)
            result = self._run_command(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-re",
                    "-i",
                    str(wav_path),
                    "-acodec",
                    "pcm_alaw",
                    "-ar",
                    "8000",
                    "-ac",
                    "1",
                    "-f",
                    "rtsp",
                    "-rtsp_transport",
                    "tcp",
                    url,
                ],
                capture_output=True,
                timeout=20,
                check=False,
            )
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace")
            raise CameraError(f"ffmpeg backchannel failed: {stderr.strip()}")
