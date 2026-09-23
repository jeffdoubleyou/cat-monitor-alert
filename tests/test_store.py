from pathlib import Path

from cat_monitor.store import SnapshotStore


def test_store_disabled_without_root() -> None:
    store = SnapshotStore(None, frame_limit=5, detection_limit=5)
    assert store.save_frame(b"jpeg") is None
    assert store.list_frames() == []


def test_store_keeps_last_n_frames(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path, frame_limit=2, detection_limit=2, clock=lambda: 1000)
    first = store.save_frame(b"one")
    second = store.save_frame(b"two")
    third = store.save_frame(b"three")
    names = {path.name for path in store.list_frames()}
    assert first is not None and first.name not in names
    assert second is not None and second.name in names
    assert third is not None and third.name in names
    assert len(store.list_frames()) == 2


def test_store_rejects_path_traversal(tmp_path: Path) -> None:
    store = SnapshotStore(tmp_path, frame_limit=2)
    store.save_frame(b"frame")
    assert store.resolve("frames", "../detections/x.jpg") is None
    assert store.resolve("frames", "/etc/passwd") is None
    name = store.list_frames()[0].name
    assert store.resolve("frames", name) is not None
