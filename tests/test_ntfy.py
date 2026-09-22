from cat_monitor.detector import Detection, DetectionResult
from cat_monitor.ntfy import NtfyClient, build_headers


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "ok") -> None:
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.status_code = 200

    def put(self, url, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
        return FakeResponse(self.status_code)


def test_build_headers_includes_bearer_token() -> None:
    headers = build_headers(
        title="Cat detected",
        message="hello",
        priority="high",
        filename="cat.jpg",
        token="abc123",
    )
    assert headers["Authorization"] == "Bearer abc123"
    assert headers["Filename"] == "cat.jpg"
    assert headers["Message"] == "hello"


def test_send_alert_puts_jpeg() -> None:
    session = FakeSession()
    client = NtfyClient("https://ntfy.sh", "cats", session=session, token="tok")
    result = DetectionResult((Detection("cat", 0.77, (0, 0, 1, 1)),))
    client.send_alert(result, b"jpeg-bytes")
    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["url"] == "https://ntfy.sh/cats"
    assert call["data"] == b"jpeg-bytes"
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert "77%" in call["headers"]["Message"]
    assert call["headers"]["Filename"].endswith(".jpg")


def test_send_test_puts_text() -> None:
    session = FakeSession()
    client = NtfyClient("https://ntfy.sh", "cats", session=session)
    client.send_test()
    assert session.calls[0]["url"] == "https://ntfy.sh/cats"
    assert session.calls[0]["data"] == "Cat monitor can reach ntfy."
    assert "test" in session.calls[0]["headers"]["Title"]
