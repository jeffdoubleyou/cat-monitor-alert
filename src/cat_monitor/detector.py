"""YOLO-based cat detection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    box: tuple[int, int, int, int]


@dataclass(frozen=True)
class DetectionResult:
    detections: tuple[Detection, ...] = field(default_factory=tuple)

    @property
    def has_cat(self) -> bool:
        return bool(self.detections)

    @property
    def best(self) -> Detection | None:
        if not self.detections:
            return None
        return max(self.detections, key=lambda item: item.confidence)


class CatDetector:
    """Run a YOLO model and keep detections whose labels are in ``classes``."""

    def __init__(
        self,
        model_path: str = "yolo11n.pt",
        confidence: float = 0.45,
        classes: list[str] | None = None,
        device: str = "cpu",
        model: Any | None = None,
    ) -> None:
        self.model_path = model_path
        self.confidence = confidence
        self.classes = [item.lower() for item in (classes or ["cat"])]
        self.device = device
        self._model = model

    def _load(self) -> Any:
        if self._model is None:
            from ultralytics import YOLO

            logger.info("Loading YOLO model %s on %s", self.model_path, self.device)
            self._model = YOLO(self.model_path)
        return self._model

    def ensure_loaded(self) -> None:
        """Load the YOLO weights so the first camera tick is not a surprise pause."""
        self._load()

    def detect(self, frame: np.ndarray) -> DetectionResult:
        model = self._load()
        result = model.predict(
            frame,
            verbose=False,
            device=self.device,
            conf=self.confidence,
        )[0]
        names = result.names
        found: list[Detection] = []
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return DetectionResult()
        for box in boxes:
            class_id = int(box.cls[0])
            label = str(names[class_id]).lower()
            if label not in self.classes:
                continue
            confidence = float(box.conf[0])
            x1, y1, x2, y2 = (int(value) for value in box.xyxy[0].tolist())
            found.append(Detection(label=label, confidence=confidence, box=(x1, y1, x2, y2)))
        return DetectionResult(tuple(found))

    def annotate(self, frame: np.ndarray, result: DetectionResult) -> np.ndarray:
        annotated = frame.copy()
        for detection in result.detections:
            x1, y1, x2, y2 = detection.box
            caption = f"{detection.label} {detection.confidence:.0%}"
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 180, 255), 2)
            cv2.putText(
                annotated,
                caption,
                (x1, max(20, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 180, 255),
                2,
                cv2.LINE_AA,
            )
        return annotated
