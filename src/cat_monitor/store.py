"""Persist recent camera frames and cat detections, with a rolling cap."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class SnapshotStore:
    """Write JPEGs under ``frames/`` and ``detections/``, then prune oldest files."""

    def __init__(
        self,
        root: str | Path | None,
        *,
        frame_limit: int = 60,
        detection_limit: int = 50,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.root = Path(root) if root else None
        self.frame_limit = max(0, int(frame_limit))
        self.detection_limit = max(0, int(detection_limit))
        self._clock = clock
        self._lock = threading.Lock()
        self._seq = 0
        if self.root is not None:
            self.frames_dir = self.root / "frames"
            self.detections_dir = self.root / "detections"
        else:
            self.frames_dir = None
            self.detections_dir = None

    @property
    def enabled(self) -> bool:
        return self.root is not None

    def save_frame(self, jpeg: bytes) -> Path | None:
        if not jpeg or self.frames_dir is None or self.frame_limit <= 0:
            return None
        return self._save(self.frames_dir, "frame", jpeg, self.frame_limit)

    def save_detection(self, jpeg: bytes, confidence: float = 0.0) -> Path | None:
        if not jpeg or self.detections_dir is None or self.detection_limit <= 0:
            return None
        score = max(0, min(99, int(round(confidence * 100))))
        return self._save(self.detections_dir, f"cat-{score:02d}", jpeg, self.detection_limit)

    def list_frames(self) -> list[Path]:
        return self._list(self.frames_dir)

    def list_detections(self) -> list[Path]:
        paths = self._list(self.detections_dir)
        if self.root is not None:
            legacy = [path for path in self.root.glob("cat-*.jpg") if path.is_file()]
            paths.extend(legacy)
            paths.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return paths

    def resolve(self, kind: str, name: str) -> Path | None:
        """Return a file in the store if ``name`` is a simple basename that exists."""
        if not name or Path(name).name != name or ".." in name:
            return None
        if kind == "frames" and self.frames_dir is not None:
            path = self.frames_dir / name
        elif kind == "detections" and self.detections_dir is not None:
            path = self.detections_dir / name
            if not path.is_file() and self.root is not None:
                path = self.root / name
        else:
            return None
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg"}:
            return path
        return None

    def _save(self, directory: Path, prefix: str, jpeg: bytes, limit: int) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._seq += 1
            stamp = int(self._clock())
            path = directory / f"{prefix}-{stamp}-{self._seq:04d}.jpg"
            path.write_bytes(jpeg)
            self._prune(directory, limit)
        logger.debug("Wrote %s", path)
        return path

    def _list(self, directory: Path | None) -> list[Path]:
        if directory is None or not directory.is_dir():
            return []
        files = [path for path in directory.glob("*.jpg") if path.is_file()]
        files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        return files

    def _prune(self, directory: Path, limit: int) -> None:
        files = sorted(directory.glob("*.jpg"), key=lambda item: (item.stat().st_mtime, item.name))
        extra = len(files) - limit
        if extra <= 0:
            return
        for path in files[:extra]:
            try:
                path.unlink()
            except OSError as exc:
                logger.warning("Could not prune %s: %s", path, exc)
