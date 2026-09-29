from pathlib import Path

from app.state.login import LoginScreenState
from app.workflow.account_login import AccountLoginConfig, AccountLoginController, AccountLoginPhase


class Detector:
    def detect(self, *args, **kwargs):
        return type("D", (), {"state": LoginScreenState.LOGIN_SCREEN})()


class Logout:
    def __init__(self): self.calls = 0
    def logout(self, *args, **kwargs): self.calls += 1


def test_wait_login_reconciles_existing_home_without_allocating_account():
    c = object.__new__(AccountLoginController)
    c.phase = AccountLoginPhase.WAIT_LOGIN_SCREEN
    c.current = None
    c.config = AccountLoginConfig([], [], Path("u"), [], Path("s"), logout_templates=object())
    c.logout_action = Logout()
    c.detector = Detector()
    c._screen = lambda: object()
    c.reconcile_existing_home()
    assert c.logout_action.calls == 1
    assert c.current is None
