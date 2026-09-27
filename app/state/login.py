from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from app.vision import VisionDetector

class LoginScreenState(str, Enum):
    UNKNOWN = "unknown"
    LOGIN_SCREEN = "login_screen"
    LOGGED_IN = "home_screen"

@dataclass(frozen=True)
class LoginDetection:
    state: LoginScreenState
    confidence: float = 0.0
    evidence: str | None = None

class LoginStateDetector:
    def __init__(self, vision: VisionDetector | None = None):
        self.vision = vision or VisionDetector()

    def detect(self, screen, *, login_templates, logged_in_templates, threshold: float = 0.80, logged_in_threshold: float | None = None) -> LoginDetection:
        # Login screen is deliberately conservative: it must meet the configured
        # threshold before we allow any physical input.
        best_login = LoginDetection(LoginScreenState.UNKNOWN)
        for template in login_templates:
            r = self.vision.find_template(screen, "login_screen", template, threshold).match
            if r.confidence > best_login.confidence:
                best_login = LoginDetection(LoginScreenState.LOGIN_SCREEN if r.found else LoginScreenState.UNKNOWN, r.confidence, str(template))
        if best_login.state == LoginScreenState.LOGIN_SCREEN:
            return best_login

        # Logged-in/home screens often contain animations, counters and other
        # changing pixels. They therefore use a separate, slightly more tolerant
        # threshold. The caller additionally requires consecutive confirmations.
        li_threshold = logged_in_threshold if logged_in_threshold is not None else threshold
        best_home = LoginDetection(LoginScreenState.UNKNOWN)
        for template in logged_in_templates:
            r = self.vision.find_template(screen, "logged_in", template, li_threshold).match
            if r.confidence > best_home.confidence:
                best_home = LoginDetection(LoginScreenState.LOGGED_IN if r.found else LoginScreenState.UNKNOWN, r.confidence, str(template))
        return best_home
