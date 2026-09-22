from types import SimpleNamespace

import numpy as np

from cat_monitor.detector import CatDetector, Detection, DetectionResult


class FakeBoxes(list):
    pass


class FakeBox:
    def __init__(self, label_id: int, confidence: float, xyxy: list[float]) -> None:
        self.cls = [label_id]
        self.conf = [confidence]
        self.xyxy = [SimpleNamespace(tolist=lambda: xyxy)]


class FakePredictResult:
    def __init__(self, boxes: list[FakeBox]) -> None:
        self.names = {0: "person", 15: "cat", 16: "dog"}
        self.boxes = boxes


class FakeModel:
    def __init__(self, boxes: list[FakeBox]) -> None:
        self.boxes = boxes

    def predict(self, frame, **kwargs):
        assert kwargs["conf"] == 0.45
        return [FakePredictResult(self.boxes)]


def test_detects_only_configured_classes() -> None:
    model = FakeModel(
        [
            FakeBox(0, 0.99, [0, 0, 10, 10]),
            FakeBox(15, 0.88, [5, 5, 40, 40]),
            FakeBox(16, 0.95, [1, 1, 2, 2]),
        ]
    )
    detector = CatDetector(model=model, classes=["cat"])
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    result = detector.detect(frame)
    assert result.has_cat
    assert result.best is not None
    assert result.best.label == "cat"
    assert result.best.confidence == 0.88
    assert result.best.box == (5, 5, 40, 40)
    assert len(result.detections) == 1


def test_empty_when_no_matching_class() -> None:
    detector = CatDetector(model=FakeModel([FakeBox(0, 0.99, [0, 0, 10, 10])]))
    result = detector.detect(np.zeros((16, 16, 3), dtype=np.uint8))
    assert not result.has_cat
    assert result.best is None


def test_annotate_draws_box() -> None:
    detector = CatDetector(model=FakeModel([]))
    frame = np.zeros((80, 80, 3), dtype=np.uint8)
    result = DetectionResult((Detection("cat", 0.91, (10, 10, 40, 40)),))
    annotated = detector.annotate(frame, result)
    assert annotated.shape == frame.shape
    assert not np.array_equal(annotated, frame)
