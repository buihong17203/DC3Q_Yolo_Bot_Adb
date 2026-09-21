from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from app.automation import AutomationEngine
from app.vision.template_matcher import TemplateMatcher


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "assets" / "templates"
TEMP_DIR = ROOT / "temp"


class ReplayVision:
    """Use the project's real 960x540 Tam Quốc Lệnh screenshots as live frames."""

    def __init__(self, device: "ReplayDevice") -> None:
        self.device = device
        self.matcher = TemplateMatcher(default_threshold=0.85, grayscale=True)

    def _image(self) -> np.ndarray:
        path = TEMP_DIR / self.device.state
        encoded = np.fromfile(path, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        assert image is not None, path
        return image

    def capture(self, force: bool = True):
        return self._image()

    def find_template(
        self,
        template,
        *,
        threshold=None,
        roi=None,
        scales=None,
        frame=None,
        refresh=True,
    ):
        image = frame if isinstance(frame, np.ndarray) else self._image()
        return self.matcher.find_best(
            image,
            TEMPLATE_DIR / template,
            threshold=threshold,
            roi=roi,
            scales=scales,
        )


class ReplayDevice:
    def __init__(
        self,
        *,
        state: str = "tql_home_acc1.png",
        que_done: bool = False,
        diem_done: bool = False,
        pending_reward: str | None = None,
    ) -> None:
        self.state = state
        self.que_done = que_done
        self.diem_done = diem_done
        self.pending_reward = pending_reward
        self.taps: list[tuple[str, int, int]] = []

    def get_screen_size(self) -> tuple[int, int]:
        return 960, 540

    def _show_que(self) -> None:
        self.state = (
            "tql_que_boi_after_reward.png"
            if self.que_done
            else "tql_que_boi_live.png"
        )

    def _show_diem(self) -> None:
        self.state = (
            "tql_diem_binh_after_reward.png"
            if self.diem_done
            else "tql_diem_binh_live.png"
        )

    def tap(self, x: int, y: int) -> None:
        self.taps.append((self.state, x, y))

        if self.state in {"tql_home_acc1.png", "tql_closed_home_live.png"}:
            self.state = "tql_opened_live.png"
            return

        if self.state == "tql_que_boi_reward_live.png":
            self.que_done = True
            self.pending_reward = None
            self.state = "tql_que_boi_after_reward.png"
            return

        if self.state == "tql_diem_binh_reward_live.png":
            self.diem_done = True
            self.pending_reward = None
            self.state = "tql_diem_binh_after_reward.png"
            return

        # Top-right X.
        if x >= 800 and y <= 100:
            self.state = "tql_closed_home_live.png"
            return

        # Left navigation tabs.
        if x <= 220:
            if y < 210:
                self._show_que()
            else:
                self._show_diem()
            return

        # Left daily action button.
        if x >= 220 and y >= 340:
            if self.state == "tql_que_boi_live.png":
                self.pending_reward = "que_boi"
                self.state = "tql_que_boi_reward_live.png"
                return

            if self.state == "tql_diem_binh_live.png":
                self.pending_reward = "diem_binh"
                self.state = "tql_diem_binh_reward_live.png"
                return


def _runtime(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "game_day": "2026-09-21",
                "accounts": [
                    {
                        "id": "acc_001",
                        "tasks": {
                            "tam_quoc_lenh": {
                                "status": "NOT_STARTED",
                                "que_boi": "NOT_STARTED",
                                "diem_binh": "NOT_STARTED",
                                "rewards": [],
                                "error": None,
                            }
                        },
                    }
                ],
                "events": [],
            }
        ),
        encoding="utf-8",
    )


def _run(device: ReplayDevice, runtime: Path):
    vision = ReplayVision(device)
    engine = AutomationEngine(device, vision)
    return engine.execute_action(
        engine.create_context(),
        {
            "action": "tam_quoc_lenh",
            "account_id": "acc_001",
            "runtime_file": str(runtime),
            "timeout": 2,
            "open_timeout": 1,
            "state_timeout": 1,
            "interval": 0.01,
        },
    )


def test_tam_quoc_lenh_real_live_images_complete_from_home(tmp_path) -> None:
    runtime = tmp_path / "runtime.json"
    _runtime(runtime)

    device = ReplayDevice()
    result = _run(device, runtime)

    assert result.success
    assert device.state == "tql_closed_home_live.png"

    state = json.loads(runtime.read_text(encoding="utf-8"))["accounts"][0]["tasks"]["tam_quoc_lenh"]
    assert state == {
        "status": "DONE",
        "que_boi": "DONE",
        "diem_binh": "DONE",
        "rewards": ["5 Quẻ lành", "20 Nguyên linh ngọc"],
        "error": None,
    }

    # HOME entry, Quẻ bói tab, free action, reward dismiss,
    # Điểm binh tab, free action, reward dismiss, final X.
    assert len(device.taps) == 8


def test_tam_quoc_lenh_resumes_from_interrupted_reward_popup(tmp_path) -> None:
    runtime = tmp_path / "runtime.json"
    _runtime(runtime)

    device = ReplayDevice(
        state="tql_que_boi_reward_live.png",
        pending_reward="que_boi",
    )
    result = _run(device, runtime)

    assert result.success
    assert device.state == "tql_closed_home_live.png"

    state = json.loads(runtime.read_text(encoding="utf-8"))["accounts"][0]["tasks"]["tam_quoc_lenh"]
    assert state["status"] == "DONE"
    assert state["que_boi"] == "DONE"
    assert state["diem_binh"] == "DONE"
    assert state["rewards"] == ["5 Quẻ lành", "20 Nguyên linh ngọc"]


def test_tam_quoc_lenh_accepts_already_used_paid_states_without_tapping_them(tmp_path) -> None:
    runtime = tmp_path / "runtime.json"
    _runtime(runtime)

    device = ReplayDevice(
        state="tql_que_boi_after_reward.png",
        que_done=True,
        diem_done=True,
    )
    result = _run(device, runtime)

    assert result.success
    assert device.state == "tql_closed_home_live.png"

    # No tap may hit the left paid action area while a completed branch is shown.
    paid_area_taps = [
        (state, x, y)
        for state, x, y in device.taps
        if state in {
            "tql_que_boi_after_reward.png",
            "tql_diem_binh_after_reward.png",
        }
        and x >= 220
        and y >= 340
    ]
    assert paid_area_taps == []
