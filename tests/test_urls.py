from cat_monitor.urls import inject_credentials, redact_url


def test_injects_credentials_when_missing() -> None:
    url = inject_credentials("rtsp://10.0.0.8:554/stream1", "admin", "p@ss:word")
    assert url == "rtsp://admin:p%40ss%3Aword@10.0.0.8:554/stream1"


def test_leaves_existing_userinfo_alone() -> None:
    original = "rtsp://user:pw@10.0.0.8/stream"
    assert inject_credentials(original, "admin", "secret") == original


def test_redacts_userinfo() -> None:
    assert (
        redact_url("rtsp://admin:secret@10.0.0.8:554/path")
        == "rtsp://***:***@10.0.0.8:554/path"
    )
