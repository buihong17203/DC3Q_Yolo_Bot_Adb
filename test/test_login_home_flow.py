from pathlib import Path

import yaml
from PIL import Image

from app.state.login import LoginScreenState, LoginStateDetector
from app.workflow.account_login import AccountLoginPhase, redact_runtime_screenshot


ROOT = Path(__file__).parents[1]


def test_flow_has_home_event_phase_before_logout():
    assert AccountLoginPhase.PROCESS_HOME_EVENTS.value == "process_home_events"


def test_runtime_login_screenshot_is_redacted():
    image = Image.new("RGB", (960, 540), "white")
    redacted = redact_runtime_screenshot(image, authentication=True)
    assert redacted.getpixel((480, 220)) == (0, 0, 0)
    assert redacted.getpixel((10, 10)) == (255, 255, 255)


def test_logged_in_detector_uses_existing_noi_chinh_template():
    login = yaml.safe_load(
        (ROOT / "config/dc3q/stars/dang-nhap.yaml").read_text(encoding="utf-8")
    )["login"]
    templates = [ROOT / path for path in login["templates"]["logged_in"]]
    assert [path.name for path in templates] == ["screen_noi-chinh_01.png"]
    assert all(path.is_file() for path in templates)
    detector = LoginStateDetector()
    for suffix in ("01", "02", "03", "07", "08", "09"):
        result = detector.detect(
            Image.open(ROOT / f"data/img/templates/stars/home/full screen/full-screen_base_{suffix}.png").convert("RGB"),
            login_templates=[],
            logged_in_templates=templates,
            logged_in_threshold=0.55,
        )
        assert result.state == LoginScreenState.LOGGED_IN
