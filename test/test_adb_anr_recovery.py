from types import SimpleNamespace

from app.adb.input import AdbInput


class Client:
    def __init__(self):
        self.calls = []
        self.focus = iter([
            "mCurrentFocus=Application Not Responding: com.daichien.mobile",
            "mCurrentFocus=Window com.daichien.mobile/com.qtz.game.main.Q2",
        ])

    def shell(self, serial, *args, timeout=None):
        self.calls.append(args)
        if args == ("dumpsys", "window", "windows"):
            return next(self.focus)
        return ""


def test_anr_wait_is_guarded_and_verified():
    client = Client()
    value = AdbInput(client, SimpleNamespace(serial="emulator-5554"))

    assert value.recover_anr_wait() is True
    assert ("input", "tap", "324", "332") in client.calls


def test_no_anr_means_no_tap():
    client = Client()
    client.focus = iter(["mCurrentFocus=Window com.daichien.mobile/com.qtz.game.main.Q2"])
    value = AdbInput(client, SimpleNamespace(serial="emulator-5554"))

    assert value.recover_anr_wait() is False
    assert not any(call[:2] == ("input", "tap") for call in client.calls)