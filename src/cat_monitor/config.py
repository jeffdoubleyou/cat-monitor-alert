"""Environment-driven configuration."""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and an optional .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    camera_host: str = ""
    camera_onvif_port: int = 80
    camera_user: str = ""
    camera_password: str = ""
    camera_onvif_https: bool = False
    camera_onvif_timeout: int = 10
    camera_rtsp_url: str = ""
    camera_profile_index: int = 0

    snapshot_interval_seconds: float = 5.0
    rtsp_transport: str = "tcp"
    capture_timeout_seconds: float = 15.0

    yolo_model: str = "yolo11n.pt"
    detect_classes: str = "cat"
    detect_confidence: float = 0.45
    inference_device: str = "cpu"

    alert_cooldown_seconds: float = 60.0
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str = ""
    ntfy_token: str = ""
    ntfy_priority: str = "high"
    ntfy_title: str = "Cat detected"

    onvif_audio_clip_token: str = ""
    onvif_audio_repeat_cycles: int = 1
    audio_backchannel_url: str = ""
    camera_http_port: int = 80

    tapo_username: str = "admin"
    tapo_cloud_password: str = ""
    tapo_alarm_seconds: float = 3.0
    tapo_alarm_sound: str = ""

    snapshot_dir: str = ""
    log_level: str = "INFO"
    dry_run: bool = False

    @field_validator("rtsp_transport")
    @classmethod
    def _normalize_transport(cls, value: str) -> str:
        transport = value.strip().lower()
        if transport not in {"tcp", "udp"}:
            raise ValueError("RTSP_TRANSPORT must be 'tcp' or 'udp'")
        return transport

    @field_validator("detect_confidence")
    @classmethod
    def _check_confidence(cls, value: float) -> float:
        if not 0 < value <= 1:
            raise ValueError("DETECT_CONFIDENCE must be between 0 and 1")
        return value

    @field_validator("snapshot_interval_seconds", "alert_cooldown_seconds", "capture_timeout_seconds", "tapo_alarm_seconds")
    @classmethod
    def _positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("duration settings must be greater than 0")
        return value

    @property
    def detect_class_list(self) -> list[str]:
        return [item.strip().lower() for item in self.detect_classes.split(",") if item.strip()]

    @property
    def ntfy_url(self) -> str:
        return f"{self.ntfy_server.rstrip('/')}/{self.ntfy_topic}"

    def require_camera(self) -> None:
        if not self.camera_rtsp_url and not self.camera_host:
            raise ValueError("CAMERA_HOST or CAMERA_RTSP_URL is required")
        if not self.camera_rtsp_url and (not self.camera_user or not self.camera_password):
            raise ValueError("CAMERA_USER and CAMERA_PASSWORD are required for ONVIF discovery")

    def require_ntfy(self) -> None:
        if not self.ntfy_topic:
            raise ValueError("NTFY_TOPIC is required")
