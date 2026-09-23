from cat_monitor.tapo import (
    TapoAudioError,
    TapoSiren,
    alert_type_names,
    resolve_alarm_type,
    usr_def_audio_ids,
)


class FakeTapo:
    def __init__(self, host, user, password) -> None:
        self.host = host
        self.user = user
        self.password = password
        self.started = False
        self.stopped = False
        self.volume = None

    def setSpeakerVolume(self, volume):
        self.volume = volume

    def startManualAlarm(self):
        self.started = True

    def stopManualAlarm(self):
        self.stopped = True


def test_tapo_siren_starts_and_stops() -> None:
    client = FakeTapo("192.168.0.181", "admin", "cloud")
    siren = TapoSiren(
        "192.168.0.181",
        "admin",
        "cloud",
        duration_seconds=0.01,
        client_factory=lambda *args, **kwargs: client,
        sleeper=lambda _delay: None,
    )
    siren.play()
    assert client.started is True
    assert client.stopped is True
    assert client.volume == 100


def test_email_username_logs_in_as_admin() -> None:
    seen: dict[str, str] = {}

    def factory(host, user, password):
        seen["user"] = user
        return FakeTapo(host, user, password)

    siren = TapoSiren(
        "192.168.0.181",
        "person@example.com",
        "cloud",
        duration_seconds=0.01,
        client_factory=factory,
        sleeper=lambda _delay: None,
    )
    siren.play()
    assert seen["user"] == "admin"


def test_tapo_login_failure_is_wrapped() -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("Invalid authentication data")

    siren = TapoSiren("192.168.0.181", "admin", "wrong", client_factory=boom)
    try:
        siren.play()
    except TapoAudioError as exc:
        assert "TAPO_CLOUD_PASSWORD" in str(exc)
    else:
        raise AssertionError("expected TapoAudioError")


def test_usr_def_audio_ids_use_start_file_when_empty() -> None:
    assert usr_def_audio_ids(
        {
            "msg_alarm": {
                "capability": {"usr_def_start_file_id": "8195"},
                "usr_def_audio": [],
            }
        }
    ) == [8195]


def test_usr_def_audio_ids_prefer_uploaded_clips() -> None:
    assert usr_def_audio_ids(
        {
            "msg_alarm": {
                "capability": {"usr_def_start_file_id": "8195"},
                "usr_def_audio": [{"id": "8196"}, {"id": 8197}],
            }
        }
    ) == [8196, 8197, 8195]


class FakeClipTapo:
    def __init__(self, host, user, password) -> None:
        self.played: list[tuple[int, bool]] = []
        self.volume = None

    def setSpeakerVolume(self, volume):
        self.volume = volume

    def startManualAlarm(self):
        raise RuntimeError("UNSUPPORTED_METHOD")

    def getAlertConfig(self, **kwargs):
        return {
            "msg_alarm": {
                "capability": {"usr_def_start_file_id": "8195"},
                "usr_def_audio": [],
            }
        }

    def testUsrDefAudio(self, audio_id, enabled, force=1):
        self.played.append((audio_id, enabled))


def test_tapo_siren_falls_back_to_usr_def_audio() -> None:
    client = FakeClipTapo("192.168.0.181", "admin", "cloud")
    siren = TapoSiren(
        "192.168.0.181",
        "admin",
        "cloud",
        duration_seconds=0.01,
        client_factory=lambda *args, **kwargs: client,
        sleeper=lambda _delay: None,
    )
    siren.play()
    assert client.played == [(8195, True), (8195, False)]
    assert client.volume == 100


def test_alert_type_names_from_camera_payload() -> None:
    assert alert_type_names(
        {"msg_alarm": {"alert_type": {"alert_type_list": ["Siren", "Emergency", "Red Alert"]}}}
    ) == ["Siren", "Emergency", "Red Alert"]


def test_resolve_alarm_type_by_name_and_index() -> None:
    names = ["Siren", "Emergency", "Red Alert"]
    assert resolve_alarm_type("", names) is None
    assert resolve_alarm_type("siren", names) == 0
    assert resolve_alarm_type("Red-Alert", names) == 2
    assert resolve_alarm_type("1", names) == 1
    assert resolve_alarm_type("8195", names) is None
    try:
        resolve_alarm_type("meow", names)
    except TapoAudioError as exc:
        assert "meow" in str(exc)
    else:
        raise AssertionError("expected TapoAudioError")


class FakeTypedTapo(FakeClipTapo):
    def __init__(self, host, user, password) -> None:
        super().__init__(host, user, password)
        self.alarm_calls: list[dict] = []

    def setAlarm(self, enabled, soundEnabled=True, lightEnabled=True, alarmType=None, alarmVolume=None):
        self.alarm_calls.append(
            {
                "enabled": enabled,
                "soundEnabled": soundEnabled,
                "lightEnabled": lightEnabled,
                "alarmType": alarmType,
            }
        )


def test_tapo_siren_does_not_enable_motion_alarm() -> None:
    client = FakeTypedTapo("192.168.0.181", "admin", "cloud")
    siren = TapoSiren(
        "192.168.0.181",
        "admin",
        "cloud",
        duration_seconds=0.01,
        sound="red_alert",
        client_factory=lambda *args, **kwargs: client,
        sleeper=lambda _delay: None,
    )
    siren.play()
    assert client.played == [(8195, True), (8195, False)]
    assert client.alarm_calls
    assert all(call["enabled"] is False for call in client.alarm_calls)


def test_disable_detection_alarm_turns_alarm_off() -> None:
    client = FakeTypedTapo("192.168.0.181", "admin", "cloud")
    siren = TapoSiren(
        "192.168.0.181",
        "admin",
        "cloud",
        client_factory=lambda *args, **kwargs: client,
    )
    siren.disable_detection_alarm()
    assert client.alarm_calls == [
        {"enabled": False, "soundEnabled": True, "lightEnabled": False, "alarmType": None}
    ]
