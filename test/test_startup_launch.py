from pathlib import Path

from app.workflow.account_login import AccountLoginConfig, AccountLoginController


class FakeInput:
    def __init__(self, foreground):
        self.foreground = foreground
        self.commands = []

    def shell(self, *args, **kwargs):
        self.commands.append(args)
        if args[:3] == ("dumpsys", "window", "windows"):
            return self.foreground
        return ""


def controller(foreground):
    c = object.__new__(AccountLoginController)
    c.input = FakeInput(foreground)
    c.config = AccountLoginConfig([], [], Path("u"), [], Path("s"))
    return c


def test_launches_game_only_when_package_not_foreground():
    c = controller("mCurrentFocus=Window{ launcher/.Launcher }")
    c.ensure_game_active()
    assert ("monkey", "-p", "com.daichien.mobile", "1") in c.input.commands


def test_does_not_relaunch_active_game():
    c = controller("mCurrentFocus=Window{ com.daichien.mobile/.MainActivity }")
    c.ensure_game_active()
    assert ("monkey", "-p", "com.daichien.mobile", "1") not in c.input.commands
