from types import SimpleNamespace

from cat_monitor.camera import OnvifCamera, extract_clip_tokens


def test_extract_clip_tokens_from_nested_dict() -> None:
    clips = {"AudioClip": [{"token": "alarm1"}, {"Token": "beep"}]}
    assert extract_clip_tokens(clips) == ["alarm1", "beep"]


def test_extract_clip_tokens_from_object() -> None:
    clip = SimpleNamespace(token="siren")
    payload = SimpleNamespace(AudioClip=[clip])
    assert extract_clip_tokens(payload) == ["siren"]


class FakeMedia:
    def GetProfiles(self):
        return [SimpleNamespace(token="profile-1")]

    def GetStreamUri(self, **kwargs):
        assert kwargs["StreamSetup"]["Transport"]["Protocol"] == "RTSP"
        return {"Uri": "rtsp://10.0.0.8:554/Streaming/Channels/101"}


class FakeMedia2:
    def __init__(self) -> None:
        self.played: dict | None = None

    def GetProfiles(self):
        raise AssertionError("media2 profiles should not be used when media works")

    def GetAudioClips(self):
        return {"AudioClip": [{"token": "doorbell"}]}

    def PlayAudioClip(self, **kwargs):
        self.played = kwargs


class FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        self.media2_service = FakeMedia2()

    def media(self):
        return FakeMedia()

    def media2(self):
        return self.media2_service


def test_get_rtsp_url_injects_credentials() -> None:
    camera = OnvifCamera(
        "10.0.0.8",
        80,
        "admin",
        "secret",
        client_factory=FakeClient,
    )
    assert camera.get_rtsp_url() == "rtsp://admin:secret@10.0.0.8:554/Streaming/Channels/101"


def test_play_sound_uses_first_clip() -> None:
    camera = OnvifCamera(
        "10.0.0.8",
        80,
        "admin",
        "secret",
        client_factory=FakeClient,
        audio_repeat_cycles=2,
    )
    camera.play_sound()
    assert camera._get_client().media2_service.played == {
        "Token": "doorbell",
        "Play": True,
        "RepeatCycles": 2,
    }


class NoClipMedia2:
    def GetAudioClips(self):
        raise RuntimeError("no clips")


class FakeClientWithoutClips(FakeClient):
    def media2(self):
        return NoClipMedia2()


def test_play_sound_falls_back_to_cgi() -> None:
    posted: dict = {}

    def fake_get(url, **kwargs):
        return SimpleNamespace(status_code=200, text="type=IP2M")

    def fake_post(url, **kwargs):
        posted["url"] = url
        posted.update(kwargs)
        return SimpleNamespace(status_code=200, text="ok")

    camera = OnvifCamera(
        "192.168.0.147",
        80,
        "admin",
        "secret",
        client_factory=FakeClientWithoutClips,
        http_get=fake_get,
        http_post=fake_post,
    )
    camera.play_sound()
    assert "audio.cgi?action=postAudio" in posted["url"]
    assert posted["files"]["file"][0] == "alert.al"
    assert posted["headers"]["Content-Type"] == "Audio/G.711A"


def test_play_sound_skips_cgi_when_probe_fails() -> None:
    def fake_get(url, **kwargs):
        return SimpleNamespace(status_code=404, text="nope")

    def fake_post(url, **kwargs):
        raise AssertionError("CGI POST should not run after a failed probe")

    camera = OnvifCamera(
        "192.168.0.181",
        2020,
        "admin1",
        "secret",
        cgi_port=80,
        client_factory=FakeClientWithoutClips,
        http_get=fake_get,
        http_post=fake_post,
    )
    try:
        camera.play_sound()
    except Exception as exc:
        message = str(exc)
        assert "CGI not available" in message
        assert "TAPO_CLOUD_PASSWORD" in message
    else:
        raise AssertionError("expected CameraError")


def test_play_sound_uses_tapo_alarm() -> None:
    class FakeTapo:
        def __init__(self, *args, **kwargs) -> None:
            self.started = False
            self.stopped = False

        def startManualAlarm(self):
            self.started = True

        def stopManualAlarm(self):
            self.stopped = True

        def setSpeakerVolume(self, volume):
            self.volume = volume

    client = FakeTapo()
    camera = OnvifCamera(
        "192.168.0.181",
        2020,
        "admin1",
        "onvif-secret",
        tapo_username="admin",
        tapo_password="cloud-secret",
        tapo_alarm_seconds=0.01,
        client_factory=FakeClientWithoutClips,
        tapo_client_factory=lambda *args, **kwargs: client,
    )
    camera.play_sound()
    assert client.started is True
    assert client.stopped is True
    assert client.volume == 100

