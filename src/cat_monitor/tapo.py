"""Tapo proprietary alarm/siren (C100 and similar have no ONVIF speaker)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_USR_DEF_AUDIO_ID = 8195
_CUSTOM_CLIP_ID_MIN = 8195


def tapo_login_username(username: str) -> str:
    """Tapo HTTPS login is always ``admin``; an email is the cloud account, not the API user."""
    value = (username or "admin").strip()
    if not value or "@" in value:
        return "admin"
    return value


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def usr_def_audio_ids(config: Any) -> list[int]:
    """Clip IDs from ``getAlertConfig``, falling back to Tapo's built-in start file id."""
    msg_alarm: Any = config
    if isinstance(config, dict):
        msg_alarm = config.get("msg_alarm", config)
    clips: list[Any] = []
    capability: dict[str, Any] = {}
    if isinstance(msg_alarm, dict):
        raw_clips = msg_alarm.get("usr_def_audio") or []
        if isinstance(raw_clips, list):
            clips = raw_clips
        elif raw_clips:
            clips = [raw_clips]
        cap = msg_alarm.get("capability")
        if isinstance(cap, dict):
            capability = cap

    ids: list[int] = []
    for clip in clips:
        if isinstance(clip, dict):
            parsed = _as_int(clip.get("id") or clip.get("file_id"))
        else:
            parsed = _as_int(clip)
        if parsed is not None and parsed not in ids:
            ids.append(parsed)

    start_id = _as_int(capability.get("usr_def_start_file_id"))
    if start_id is not None and start_id not in ids:
        ids.append(start_id)
    if not ids:
        ids.append(_DEFAULT_USR_DEF_AUDIO_ID)
    return ids


def normalize_sound_name(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def alert_type_names(payload: Any) -> list[str]:
    """Built-in Tapo sounds from ``getAlertTypeList`` (Siren, Emergency, Red Alert, …)."""
    node: Any = payload
    if isinstance(node, dict) and "msg_alarm" in node:
        node = node["msg_alarm"]
    if isinstance(node, dict) and "alert_type" in node:
        node = node["alert_type"]
    if isinstance(node, dict):
        node = node.get("alert_type_list") or node.get("siren_type_list") or []
    if not isinstance(node, list):
        return []
    return [str(item) for item in node if str(item).strip()]


def custom_clip_id(sound: str) -> int | None:
    """Return a user-defined clip id when ``sound`` is a numeric Tapo file id."""
    parsed = _as_int((sound or "").strip())
    if parsed is not None and parsed >= _CUSTOM_CLIP_ID_MIN:
        return parsed
    return None


def resolve_alarm_type(sound: str, type_names: list[str]) -> int | None:
    """Map TAPO_ALARM_SOUND to the camera's 0-based ``alarm_type`` index."""
    raw = (sound or "").strip()
    if not raw:
        return None
    if custom_clip_id(raw) is not None:
        return None
    parsed = _as_int(raw)
    if parsed is not None:
        return parsed
    needle = normalize_sound_name(raw)
    aliases = {"tone": "emergency", "redalarm": "redalert"}
    needle = aliases.get(needle, needle)
    for index, name in enumerate(type_names):
        if normalize_sound_name(name) == needle:
            return index
    available = ", ".join(type_names) if type_names else "Siren, Emergency, Red Alert"
    raise TapoAudioError(f"Unknown TAPO_ALARM_SOUND={sound!r}. Available: {available}")


class TapoAudioError(RuntimeError):
    """Could not trigger the Tapo camera siren."""


class TapoSiren:
    """Play a sound on a Tapo camera speaker via the HTTPS API."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        duration_seconds: float = 3.0,
        sound: str = "",
        client_factory: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.host = host
        self.username = tapo_login_username(username)
        self.password = password
        self.duration_seconds = duration_seconds
        self.sound = (sound or "").strip()
        self._client_factory = client_factory
        self._sleeper = sleeper

    def play(self) -> None:
        factory = self._client_factory
        if factory is None:
            from pytapo import Tapo

            factory = Tapo
        try:
            client = factory(self.host, self.username, self.password)
        except Exception as exc:  # noqa: BLE001
            raise TapoAudioError(
                f"Tapo login failed ({exc}). Use the Tapo app password as TAPO_CLOUD_PASSWORD "
                "(not the ONVIF camera account), and enable Tapo Lab > Third-Party Compatibility."
            ) from exc

        try:
            setter = getattr(client, "setSpeakerVolume", None)
            if callable(setter):
                setter(100)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tapo setSpeakerVolume skipped: %s", exc)

        self._apply_sound_type(client)

        errors: list[str] = []
        if self._play_manual_alarm(client, errors):
            return
        if self._play_usr_def_audio(client, errors):
            return
        raise TapoAudioError("Tapo speaker failed: " + "; ".join(errors))

    def _play_manual_alarm(self, client: Any, errors: list[str]) -> bool:
        starter = getattr(client, "startManualAlarm", None)
        if not callable(starter):
            return False
        try:
            starter()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"startManualAlarm: {exc}")
            logger.debug("Tapo startManualAlarm unavailable: %s", exc)
            return False

        logger.info("Triggered Tapo manual alarm for %.1fs", self.duration_seconds)
        try:
            self._sleeper(self.duration_seconds)
        finally:
            stopper = getattr(client, "stopManualAlarm", None)
            if callable(stopper):
                try:
                    stopper()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Tapo stopManualAlarm failed: %s", exc)
        return True

    def _play_usr_def_audio(self, client: Any, errors: list[str]) -> bool:
        tester = getattr(client, "testUsrDefAudio", None)
        if not callable(tester):
            errors.append("testUsrDefAudio is not supported")
            return False

        for audio_id in self._selected_audio_ids(client):
            try:
                tester(audio_id, True)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"testUsrDefAudio {audio_id}: {exc}")
                logger.debug("Tapo testUsrDefAudio(%s) failed: %s", audio_id, exc)
                continue

            logger.info("Played Tapo alarm clip %s for %.1fs", audio_id, self.duration_seconds)
            try:
                self._sleeper(self.duration_seconds)
            finally:
                try:
                    tester(audio_id, False)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Tapo testUsrDefAudio stop failed: %s", exc)
            return True
        return False

    def _selected_audio_ids(self, client: Any) -> list[int]:
        clip = custom_clip_id(self.sound)
        if clip is not None:
            return [clip]
        return self._audio_ids(client)

    def _apply_sound_type(self, client: Any) -> None:
        if not self.sound or custom_clip_id(self.sound) is not None:
            return
        names = self._type_names(client)
        type_index = resolve_alarm_type(self.sound, names)
        if type_index is None:
            return
        setter = getattr(client, "setAlarm", None)
        if not callable(setter):
            logger.debug("Tapo setAlarm missing; cannot select sound %s", self.sound)
            return
        try:
            setter(
                True,
                soundEnabled=True,
                lightEnabled=False,
                alarmType=type_index,
                alarmVolume="high",
            )
        except Exception as exc:  # noqa: BLE001
            raise TapoAudioError(f"Tapo setAlarm sound {self.sound!r} failed: {exc}") from exc
        label = names[type_index] if 0 <= type_index < len(names) else str(type_index)
        logger.info("Selected Tapo alarm sound %s (type %s)", label, type_index)

    def _type_names(self, client: Any) -> list[str]:
        getter = getattr(client, "getAlertTypeList", None)
        if not callable(getter):
            return ["Siren", "Emergency", "Red Alert"]
        try:
            return alert_type_names(getter()) or ["Siren", "Emergency", "Red Alert"]
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tapo getAlertTypeList skipped: %s", exc)
            return ["Siren", "Emergency", "Red Alert"]

    def _audio_ids(self, client: Any) -> list[int]:
        getter = getattr(client, "getAlertConfig", None)
        if not callable(getter):
            return [_DEFAULT_USR_DEF_AUDIO_ID]
        try:
            try:
                config = getter(includeCapability=True, includeUserDefinedAudio=True)
            except TypeError:
                config = getter()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tapo getAlertConfig skipped: %s", exc)
            return [_DEFAULT_USR_DEF_AUDIO_ID]
        return usr_def_audio_ids(config)
