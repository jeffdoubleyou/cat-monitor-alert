from urllib.error import HTTPError
from urllib.request import urlopen

import numpy as np

from cat_monitor.capture import encode_jpeg
from cat_monitor.store import SnapshotStore
from cat_monitor.ui import start_snapshot_ui


def test_ui_serves_gallery_and_jpeg(tmp_path) -> None:
    store = SnapshotStore(tmp_path, frame_limit=5, detection_limit=5)
    jpeg = encode_jpeg(np.zeros((12, 16, 3), dtype=np.uint8))
    saved = store.save_frame(jpeg)
    assert saved is not None
    ui = start_snapshot_ui(store, host="127.0.0.1", port=0)
    try:
        home = urlopen(f"http://127.0.0.1:{ui.port}/", timeout=2).read().decode()
        assert "Recent frames" in home
        listing = urlopen(f"http://127.0.0.1:{ui.port}/api/frames", timeout=2).read().decode()
        assert saved.name in listing
        image = urlopen(f"http://127.0.0.1:{ui.port}/media/frames/{saved.name}", timeout=2).read()
        assert image == jpeg
        try:
            urlopen(f"http://127.0.0.1:{ui.port}/media/frames/missing.jpg", timeout=2)
        except HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("missing image should 404")
    finally:
        ui.stop()
