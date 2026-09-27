from pathlib import Path

import yaml
from PIL import Image

from app.actions.tai_khoan import AccountLogoutAction, LogoutTemplates


ROOT = Path(__file__).parents[1]


def _templates():
    cfg = yaml.safe_load(
        (ROOT / "config/dc3q/stars/dang-xuat.yaml").read_text(encoding="utf-8")
    )["logout"]
    return LogoutTemplates(
        *(ROOT / cfg["templates"][name] for name in ("open_tuychon", "open_cdnd", "open_dtk", "confirm_dtk")),
        ROOT / cfg["home_anchor_template"],
        tuple(cfg["home_anchor_roi"]),
        tuple(cfg["avatar_mirror_offset"]),
    ), cfg


def test_failure_frame_recognizes_noi_chinh_and_derives_avatar():
    templates, cfg = _templates()
    frame = Image.open(ROOT / "test/fixtures/logout_home.png").convert("RGB")
    point = AccountLogoutAction(None, templates)._avatar_from_noi_chinh(
        frame, templates, cfg["threshold"]
    )
    assert point == (40, 50)
