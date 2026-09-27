from pathlib import Path

import numpy as np
from PIL import Image

from app.actions.tai_khoan import AccountLogoutAction, LogoutTemplates


class _Input:
    pass


def test_avatar_is_derived_from_direct_noi_chinh_template(tmp_path: Path):
    template = np.zeros((56, 96, 3), dtype=np.uint8)
    template[5:20, 8:30] = (255, 255, 255)
    template[30:50, 55:90] = (30, 180, 240)
    template_path = tmp_path / "screen_noi-chinh_01.png"
    Image.fromarray(template).save(template_path)

    screen = np.zeros((575, 1000, 3), dtype=np.uint8)
    screen[507:563, 864:960] = template
    templates = LogoutTemplates(
        open_tuychon=tmp_path / "a.png",
        open_cdnd=tmp_path / "b.png",
        open_dtk=tmp_path / "c.png",
        confirm_dtk=tmp_path / "d.png",
        home_anchor_template=template_path,
    )

    assert AccountLogoutAction(_Input())._avatar_from_noi_chinh(screen, templates, 0.70) == (80, 61)
