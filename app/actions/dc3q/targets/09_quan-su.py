from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable
import unicodedata


def _is_military_ocr(text: str) -> bool:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    words = plain.split()
    return any(word.startswith("quan") for word in words) and any(word.startswith("su") for word in words)


@dataclass(frozen=True)
class TuiGamSpec:
    name: str
    chua_tha: Path
    da_tha: Path


@dataclass(frozen=True)
class QuanSuConfig:
    military_point: tuple[int, int]
    military_close_point: tuple[int, int]
    tranh_ba_entry: list[Path]
    home_markers: list[Path]
    main_markers: list[Path]
    detail_markers: list[Path]
    reward_tab: Path
    reward_button: Path
    unfinished_markers: list[Path]
    close_template: Path
    threshold: float = 0.60
    max_steps: int = 60
    wait_seconds: float = 0.8
    battles: int = 5
    tui_gam_specs: list[TuiGamSpec] = ()
    tui_gam_threshold: float = 0.68
    giao_tranh_entry: list[Path] = ()
    gt_battles: int = 5
    gt_tui_gam_specs: list[TuiGamSpec] = ()
    gt_tui_gam_threshold: float = 0.68
    gt_find_opponent: Path | None = None
    gt_result_continue: Path | None = None
    gt_result_banner: Path | None = None
    gt_main_markers: list[Path] = ()


class QuanSuRunner:
    """Quân sự -> Tranh Bá -> nhận thưởng hàng ngày -> đánh 5 trận (thả túi gấm, rút lui, tiếp tục) -> HOME."""
    runtime_task = "TRANH_BA"

    def __init__(self, screen_provider, adb_input, vision, config: QuanSuConfig,
                 sleep: Callable[[float], None] = default_sleep,
                 account_level_provider: Callable[[], str] | None = None):
        self.screen_provider = screen_provider
        self.input = adb_input
        self.vision = vision
        self.config = config
        self.sleep = sleep
        self.account_level_provider = account_level_provider or (lambda: "")
        self._rapid_ocr = None
        self._ocr_cache_screen = None
        self._ocr_cache_items = []

    @staticmethod
    def _plain(text: str) -> str:
        return " ".join(
            "".join(
                char for char in unicodedata.normalize("NFKD", word)
                if not unicodedata.combining(char)
            ).lower().replace("đ", "d")
            for word in text.split()
        )

    def _ocr_rows(self, screen):
        from rapidocr_onnxruntime import RapidOCR
        import numpy as np

        data = screen.data if hasattr(screen, "data") else screen
        image = np.asarray(data.convert("RGB")) if hasattr(data, "convert") else np.asarray(data)
        if self._rapid_ocr is None:
            self._rapid_ocr = RapidOCR()
        result, _ = self._rapid_ocr(image)
        return result or []

    def _ocr_items(self, screen):
        if screen is self._ocr_cache_screen:
            return self._ocr_cache_items
        items = []
        for row in self._ocr_rows(screen):
            points = row[0]
            items.append((
                self._plain(str(row[1])),
                int(sum(point[0] for point in points) / len(points)),
                int(sum(point[1] for point in points) / len(points)),
            ))
        self._ocr_cache_screen, self._ocr_cache_items = screen, items
        return items

    @staticmethod
    def _find(items, words: tuple[str, ...], *, x_min=0, x_max=9999, y_min=0, y_max=9999):
        for text, x, y in items:
            compact = text.replace(" ", "")
            if (x_min <= x <= x_max and y_min <= y <= y_max
                    and any(word.replace(" ", "") in compact for word in words)):
                return x, y
        return None

    def _match(self, screen, template: Path, threshold: float | None = None):
        value = self.config.threshold if threshold is None else threshold
        return self.vision.find_template(screen, "tranh_ba", template, value).match

    def _first(self, screen, templates: list[Path]):
        for template in templates:
            match = self._match(screen, template)
            if match.found:
                return match
        return None

    def _tap(self, match_or_point) -> None:
        if isinstance(match_or_point, tuple):
            self.input.tap(*match_or_point)
        else:
            self.input.tap(match_or_point.x + match_or_point.width // 2,
                           match_or_point.y + match_or_point.height // 2)
        self.sleep(self.config.wait_seconds)

    def _tap_tranh_ba(self, match) -> None:
        # Icon chiếm 48 px đầu; tránh vùng chữ ở đáy crop.
        if isinstance(match, tuple):
            self.input.tap(*match)
        else:
            self.input.tap(match.x + match.width // 2, match.y + 24)
        self.sleep(self.config.wait_seconds)

    @staticmethod
    def _screen_array(screen):
        import cv2
        import numpy as np
        if hasattr(screen, "data") and isinstance(screen.data, np.ndarray):
            return screen.data
        if isinstance(screen, np.ndarray):
            return screen
        if isinstance(screen, (bytes, bytearray)):
            return cv2.imdecode(np.frombuffer(screen, dtype=np.uint8), cv2.IMREAD_COLOR)
        if hasattr(screen, "convert"):
            return cv2.cvtColor(np.array(screen.convert("RGB")), cv2.COLOR_RGB2BGR)
        return cv2.imread(str(screen))

    def _is_home(self, screen) -> bool:
        if self._first(screen, self.config.home_markers) is not None:
            return True
        items = self._ocr_items(screen)
        header_home = self._find(items, ("noi chinh", "noichinh", "thanh chinh", "thanhchinh"), y_max=200)
        return header_home is not None

    def _dismiss_exit_popup(self, screen) -> bool:
        items = self._ocr_items(screen)
        full_text = " ".join(text for text, _, _ in items).replace(" ", "")
        if any(k in full_text for k in ("thoatgame", "chuacong", "chuyendaisu", "roidi")):
            huy_pos = self._find(items, ("huy", "huybo"), y_min=300)
            if huy_pos is not None:
                self._tap(huy_pos)
            else:
                self.input.tap(365, 353)
            self.sleep(self.config.wait_seconds)
            return True
        return False

    def _is_main_panel(self, screen) -> bool:
        if self._first(screen, self.config.main_markers) is not None:
            return True
        items = self._ocr_items(screen)
        return self._find(items, ("tranh ba",), y_max=120) is not None

    def _is_reward_detail(self, screen) -> bool:
        if self._first(screen, self.config.detail_markers) is not None:
            return True
        items = self._ocr_items(screen)
        return self._find(items, ("chi tiet thuong",), y_max=150) is not None

    def _find_uncast_tui_gam(self, screen, exclude: set[str] | None = None) -> tuple[str, int, int] | None:
        exclude = exclude or set()
        best_spec = None
        best_match = None
        best_score_diff = -1.0

        for spec in self.config.tui_gam_specs:
            if spec.name in exclude:
                continue
            chua_match = self.vision.find_template(
                screen, f"tui_gam_{spec.name}_chua", spec.chua_tha, self.config.tui_gam_threshold,
            ).match
            if not chua_match.found:
                continue

            da_match = self.vision.find_template(
                screen, f"tui_gam_{spec.name}_da", spec.da_tha, self.config.tui_gam_threshold,
            ).match

            if not da_match.found or chua_match.confidence > da_match.confidence:
                score_diff = chua_match.confidence - (da_match.confidence if da_match.found else 0.0)
                if score_diff > best_score_diff:
                    best_score_diff = score_diff
                    best_spec = spec
                    best_match = chua_match

        if best_match is not None and best_spec is not None:
            cx = best_match.x + best_match.width // 2
            cy = best_match.y + best_match.height // 2
            return best_spec.name, cx, cy
        return None

    def _cast_tui_gam(self, name: str, x: int, y: int) -> None:
        logger = logging.getLogger("dc3q")
        logger.info("QUAN_SU | thả túi gấm: %s từ (%d, %d) ra giữa màn hình (480, 270)", name, x, y)
        self.input.tap(x, y)
        self.sleep(0.3)
        self.input.tap(480, 270)
        self.sleep(0.3)
        self.input.swipe(x, y, 480, 270, 350)
        self.sleep(self.config.wait_seconds)

    def _retreat_confirm(self, screen):
        items = self._ocr_items(screen)
        full_text = " ".join(text for text, _, _ in items).replace(" ", "")
        has_retreat_dialog = any(k in full_text for k in ("chiendau", "luibinh", "rutlui", "muonlui", "dabattau"))
        xac_nhan = self._find(items, ("xac nhan", "xacnhan", "dong y"), x_min=450, y_min=250)
        if xac_nhan is not None:
            if has_retreat_dialog or len(full_text) < 100:
                return xac_nhan
        return None

    def _result_continue(self, screen):
        if self.config.gt_result_continue is not None:
            match_btn = self._match(screen, self.config.gt_result_continue)
            if match_btn.found:
                return match_btn.x + match_btn.width // 2, match_btn.y + match_btn.height // 2
        items = self._ocr_items(screen)
        tran_sau = self._find(
            items,
            ("tran sau", "transau", "sau"),
            x_max=200, y_min=450,
        )
        if tran_sau is not None:
            return tran_sau
        return self._find(
            items,
            ("tiep tuc", "tieptuc", "tiep", "danh tiep", "danhtiep", "khieu chien", "khieuchien", "chien tiep", "tran tiep"),
            x_min=400, y_min=250,
        )

    def _result_complete(self, screen):
        items = self._ocr_items(screen)
        hoi_thanh = self._find(
            items,
            ("hoi thanh", "hoithanh"),
            x_min=700, y_min=450,
        )
        if hoi_thanh is not None:
            return hoi_thanh
        return self._find(
            items,
            ("quay ve", "quayve", "tro ve", "trove", "roi khoi", "roikhoi", "hoan thanh", "thoat"),
            x_max=520, y_min=250,
        )

    def _is_battle_ended(self, screen) -> bool:
        if self.config.gt_result_banner is not None:
            match_banner = self._match(screen, self.config.gt_result_banner)
            if match_banner.found:
                return True
        items = self._ocr_items(screen)
        full_text = " ".join(text for text, _, _ in items).replace(" ", "")
        return any(k in full_text for k in ("thatbai", "chienbai", "chienthang", "thangloi", "tieptuc", "quayve", "roikhoi", "trove", "transau", "hoithanh", "bai", "thang"))

    @staticmethod
    def _is_battle_time() -> bool:
        """Tranh Bá chỉ đánh từ 07:01 đến 22:59 (giờ VN); ngoài giờ chỉ nhận thưởng."""
        from datetime import datetime, timezone, timedelta
        vn_time = datetime.now(timezone(timedelta(hours=7)))
        minute_of_day = vn_time.hour * 60 + vn_time.minute
        return (7 * 60 + 1) <= minute_of_day <= (22 * 60 + 59)

    def _count_hearts(self, screen) -> int:
        """Đếm số tim đỏ hiện có trên giao diện chính Tranh Bá (vùng dưới Mỗi lần chiến đấu tốn)."""
        import cv2
        arr = self._screen_array(screen)
        h, w = arr.shape[:2]
        x1 = int(670 * w / 960)
        x2 = int(880 * w / 960)
        y1 = int(115 * h / 540)
        y2 = int(160 * h / 540)
        crop = arr[y1:y2, x1:x2]
        if crop.size == 0:
            return 0
        hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV) if crop.ndim == 3 else crop
        mask = cv2.inRange(hsv, (0, 120, 120), (10, 255, 255)) | cv2.inRange(hsv, (170, 120, 120), (180, 255, 255))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        hearts = [c for c in contours if 30 < cv2.contourArea(c) < 500]
        return len(hearts)

    def _find_tb_battle_btn(self, screen):
        items = self._ocr_items(screen)
        # Tìm nút Chiến đấu / Khiêu chiến / Tấn công trên panel Tranh Bá
        point = self._find(
            items,
            ("chien dau", "chiendau", "khieu chien", "khieuchien", "tan cong", "tim doi thu", "xuat chien"),
            y_min=250,
        )
        if point is not None:
            return point
        # Tọa độ mặc định nếu giao diện đang ở main panel nhưng OCR bị bóng/hiệu ứng
        if self._is_main_panel(screen):
            return (520, 500)
        return None

    def _is_buy_turn_popup(self, items: list[tuple[str, int, int]]) -> bool:
        full_text = "".join(text for text, _, _ in items).replace(" ", "")
        # Popup hỏi tốn 20 KNB để mua 1 lượt khiêu chiến Tranh Bá
        if any(k in full_text for k in (
            "20knb", "ton20", "tieuhao20", "mua1luot", "muathem",
            "khongdu", "hetluot", "solankhieuchien"
        )):
            return True
        if ("20" in full_text or "knb" in full_text) and any(m in full_text for m in ("mua", "luot")):
            return True
        return False

    def _dismiss_buy_turn_popup(self, items: list[tuple[str, int, int]], screen=None) -> bool:
        # Bấm Hủy, tuyệt đối không bấm Xác nhận để không mất 20 KNB
        huy_btn = self._find(items, ("huy", "huybo", "dong", "thoat"), y_min=250)
        if huy_btn is not None:
            self._tap(huy_btn)
        else:
            # Tọa độ nút Hủy mặc định trên popup xác nhận chuẩn 960x540
            self.input.tap(365, 350)
        self.sleep(self.config.wait_seconds)
        return True

    def recover_home(self, initial_screen=None) -> bool:
        for _ in range(8):
            screen = initial_screen if initial_screen is not None else self.screen_provider()
            initial_screen = None
            if self._dismiss_exit_popup(screen):
                continue
            if self._is_home(screen):
                entry = self._first(screen, self.config.tranh_ba_entry)
                if entry is not None:
                    self.input.tap(*self.config.military_close_point)
                    self.sleep(self.config.wait_seconds)
                    continue
                return True
            if self._first(screen, self.config.detail_markers) is not None:
                close = self._match(screen, self.config.close_template)
                if close.found:
                    self._tap(close)
                    continue
            if self._first(screen, self.config.main_markers) is not None:
                close = self._match(screen, self.config.close_template)
                if close.found:
                    self._tap(close)
                    continue
            items = self._ocr_items(screen)
            complete = self._result_complete(screen)
            if complete is not None:
                self._tap(complete)
                continue
            retreat = self._find(items, ("rut lui", "thu quan"), x_max=300, y_min=200)
            if retreat is not None:
                self._tap(retreat)
                continue
            confirm = self._retreat_confirm(screen)
            if confirm is not None:
                self._tap(confirm)
                continue
            close_btn = self._find(items, ("tro ve", "dong", "thoat"), y_max=150)
            if close_btn is not None:
                self._tap(close_btn)
                continue
            hoi_thanh = self._find(items, ("hoi thanh", "hoithanh"), y_min=400)
            if hoi_thanh is not None:
                self._tap(hoi_thanh)
                continue
            # Nút X góc trên phải của Tranh Bá (910, 45)
            self.input.tap(910, 45)
            self.sleep(self.config.wait_seconds)
        screen = self.screen_provider()
        self._dismiss_exit_popup(screen)
        if self._is_home(screen):
            entry = self._first(screen, self.config.tranh_ba_entry)
            if entry is not None:
                self.input.tap(*self.config.military_close_point)
                self.sleep(self.config.wait_seconds)
            return True
        return False

    def _get_account_level(self) -> int | None:
        try:
            raw = str(self.account_level_provider() or "").strip()
            if raw.isdigit():
                return int(raw)
        except Exception:
            pass
        return None

    def run_tranh_ba(self) -> bool:
        logger = logging.getLogger("dc3q")
        level = self._get_account_level()
        is_low_level = (level is not None and level < 40)
        is_battle_allowed = self._is_battle_time()
        if is_low_level:
            logger.info("TRANH_BA | cấp=%s < 40 | chỉ kiểm tra nhận thưởng hàng ngày nếu có (không đánh tranh bá)", level)
        elif not is_battle_allowed:
            logger.info("TRANH_BA | ngoài khung giờ chiến đấu (07:01 - 22:59) | chỉ kiểm tra nhận thưởng hàng ngày (không đánh)")
        else:
            logger.info("TRANH_BA | cấp=%s >= 40 và trong khung giờ 07:01-22:59 | kiểm tra thưởng và đánh tranh bá", level or "N/A")

        phase = "OPEN_HOME_MENU"
        battles = 0
        total_battles = None
        result_wait_steps = 0
        confirm_wait_steps = 0
        casted_in_battle: set[str] = set()

        for _ in range(self.config.max_steps):
            screen = self.screen_provider()
            items = self._ocr_items(screen) if phase not in ("OPEN_HOME_MENU", "OPEN_TRANH_BA") else []

            if phase == "OPEN_HOME_MENU":
                # Kiểm tra nếu icon Tranh Bá đã sẵn sàng (menu đã mở trước đó)
                entry = self._first(screen, self.config.tranh_ba_entry)
                if entry is not None:
                    self._tap_tranh_ba(entry)
                    phase = "OPEN_REWARD"
                    continue
                if self._first(screen, self.config.home_markers) is None:
                    if is_low_level:
                        logger.info("TRANH_BA | cấp=%s < 40 | chưa ở HOME -> recover HOME rồi bỏ qua an toàn", level)
                        self.recover_home(screen)
                        return True
                    raise RuntimeError("Tranh Bá: chưa chứng minh HOME")
                self.input.tap(*self.config.military_point)
                self.sleep(self.config.wait_seconds)
                phase = "OPEN_TRANH_BA"
                continue

            if phase == "OPEN_TRANH_BA":
                entry = self._first(screen, self.config.tranh_ba_entry)
                if entry is None:
                    entry_ocr = self._find(self._ocr_items(screen), ("tranh ba",), x_min=80, x_max=400, y_min=300, y_max=530)
                    if entry_ocr is not None:
                        self.input.tap(*entry_ocr)
                        self.sleep(self.config.wait_seconds)
                        phase = "OPEN_REWARD"
                        continue
                    if self._is_main_panel(screen):
                        phase = "OPEN_REWARD"
                        continue
                    if is_low_level:
                        logger.info("TRANH_BA | cấp=%s < 40 | menu Quân sự không có Tranh Bá (chưa mở khóa) -> bỏ qua an toàn", level)
                        self.recover_home(screen)
                        return True
                    raise RuntimeError("Tranh Bá: menu Quân sự thiếu icon Tranh Bá")
                self._tap_tranh_ba(entry)
                phase = "OPEN_REWARD"
                continue

            if phase == "OPEN_REWARD":
                if not self._is_main_panel(screen):
                    self.sleep(self.config.wait_seconds)
                    continue
                reward_tab = self._match(screen, self.config.reward_tab)
                if not reward_tab.found:
                    # Nếu không tìm thấy tab thưởng, thử bằng OCR
                    reward_ocr = self._find(items, ("thuong", "nhan thuong"), y_min=300)
                    if reward_ocr is not None:
                        self._tap(reward_ocr)
                        phase = "CHECK_REWARD"
                        continue
                    if is_low_level or not is_battle_allowed:
                        if not self.recover_home(screen):
                            raise RuntimeError("Tranh Bá: chưa đóng về HOME")
                        logger.info("TRANH_BA | hoàn tất, đã về HOME")
                        return True
                    # Nếu level >= 40 và trong khung giờ, chuyển thẳng sang MAIN_PANEL để đánh
                    phase = "MAIN_PANEL"
                    continue
                self._tap(reward_tab)
                phase = "CHECK_REWARD"
                continue

            if phase == "CHECK_REWARD":
                if not self._is_reward_detail(screen):
                    self.sleep(self.config.wait_seconds)
                    continue
                if self._first(screen, self.config.unfinished_markers) is not None:
                    logger.info("TRANH_BA | Chưa kết thúc: hôm nay đã nhận; không bấm")
                    if is_low_level or not is_battle_allowed:
                        if not self.recover_home(screen):
                            raise RuntimeError("Tranh Bá: chưa đóng về HOME")
                        logger.info("TRANH_BA | hoàn tất, đã về HOME")
                        return True
                    # Đóng popup Chi tiết thưởng về lại Main Panel
                    close = self._match(screen, self.config.close_template)
                    if close.found:
                        self._tap(close)
                    else:
                        close_btn = self._find(items, ("tro ve", "dong", "thoat"), y_max=150)
                        if close_btn is not None:
                            self._tap(close_btn)
                        else:
                            self.input.tap(910, 45)
                            self.sleep(self.config.wait_seconds)
                    phase = "MAIN_PANEL"
                    continue

                reward = self._match(screen, self.config.reward_button)
                if not reward.found:
                    # Kiểm tra xem có phải đã nhận rồi không
                    if self._first(screen, self.config.unfinished_markers) is not None:
                        phase = "MAIN_PANEL" if (not is_low_level and is_battle_allowed) else "CLOSE_HOME"
                        continue
                    if is_low_level:
                        logger.info("TRANH_BA | cấp=%s < 40 | không thấy nút nhận thưởng (hôm nay đã nhận hoặc chưa mở) -> về HOME", level)
                        self.recover_home(screen)
                        return True
                    raise RuntimeError("Tranh Bá: Chi tiết thưởng thiếu trạng thái")
                self._tap(reward)
                logger.info("TRANH_BA | bấm Nhận thưởng")
                phase = "VERIFY_CLAIMED"
                continue

            if phase == "VERIFY_CLAIMED":
                logger.info("TRANH_BA | nhận thưởng thành công")
                if is_low_level or not is_battle_allowed:
                    if not self.recover_home(screen):
                        raise RuntimeError("Tranh Bá: chưa đóng về HOME")
                    logger.info("TRANH_BA | hoàn tất, đã về HOME")
                    return True
                # Đóng popup Chi tiết thưởng về Main Panel
                close = self._match(screen, self.config.close_template)
                if close.found:
                    self._tap(close)
                else:
                    close_btn = self._find(items, ("tro ve", "dong", "thoat"), y_max=150)
                    if close_btn is not None:
                        self._tap(close_btn)
                    else:
                        self.input.tap(910, 45)
                        self.sleep(self.config.wait_seconds)
                phase = "MAIN_PANEL"
                continue

            if phase == "CLOSE_HOME":
                if not self.recover_home(screen):
                    raise RuntimeError("Tranh Bá: chưa đóng về HOME")
                logger.info("TRANH_BA | hoàn tất, đã về HOME")
                return True

            if phase == "MAIN_PANEL":
                # Kiểm tra nếu popup mua lượt 20 KNB đang hiển thị
                if self._is_buy_turn_popup(items):
                    logger.info("TRANH_BA | phát hiện popup hỏi tốn 20 KNB mua lượt -> đã hết lượt -> bấm Hủy và về HOME")
                    self._dismiss_buy_turn_popup(items, screen)
                    self.recover_home(screen)
                    return True

                if is_low_level:
                    logger.info("TRANH_BA | cấp=%s < 40 | không đánh tranh bá -> về HOME", level)
                    if not self.recover_home(screen):
                        raise RuntimeError("Tranh Bá: chưa đóng về HOME")
                    return True

                if not is_battle_allowed:
                    logger.info("TRANH_BA | ngoài khung giờ chiến đấu (07:01 - 22:59) -> về HOME")
                    if not self.recover_home(screen):
                        raise RuntimeError("Tranh Bá: chưa đóng về HOME")
                    return True

                if total_battles is None:
                    detected_hearts = self._count_hearts(screen)
                    if 0 < detected_hearts <= 6:
                        total_battles = detected_hearts
                        logger.info("TRANH_BA | phát hiện số tim = %d -> thiết lập tổng số trận = %d", detected_hearts, total_battles)
                    else:
                        # Thử đánh tối đa theo cấu hình (mặc định 5 trận).
                        # Nếu tài khoản đã hết lượt, khi bấm Chiến đấu sẽ xuất hiện popup hỏi tốn 20 KNB mua lượt.
                        total_battles = self.config.battles or 5
                        logger.info("TRANH_BA | số tim=%d -> thiết lập tối đa %d trận (kiểm tra popup 20 KNB khi hết lượt)", detected_hearts, total_battles)

                if battles >= total_battles:
                    logger.info("TRANH_BA | đã hoàn thành đủ %d/%d trận -> về HOME", battles, total_battles)
                    if not self.recover_home(screen):
                        raise RuntimeError("Tranh Bá: chưa đóng về HOME sau khi đánh đủ trận")
                    return True

                battle_btn = self._find_tb_battle_btn(screen)
                if battle_btn is None:
                    self.sleep(self.config.wait_seconds)
                    continue
                self._tap(battle_btn)
                phase = "BATTLE_OR_FORMATION"
                continue

            if phase == "BATTLE_OR_FORMATION":
                # Kiểm tra nếu xuất hiện popup hết lượt: hỏi có tốn 20 KNB để mua 1 lượt không
                if self._is_buy_turn_popup(items):
                    logger.info("TRANH_BA | phát hiện popup hỏi tốn 20 KNB mua 1 lượt -> đã hết lượt miễn phí -> bấm Hủy và về HOME")
                    self._dismiss_buy_turn_popup(items, screen)
                    self.recover_home(screen)
                    return True

                # Kiểm tra nếu xuất hiện màn Xuất chiến
                xuat_chien = self._find(items, ("xuat chien",), x_min=600, y_min=350)
                if xuat_chien is not None:
                    self._tap(xuat_chien)
                    phase = "BATTLE"
                    continue
                # Kiểm tra nếu đã trực tiếp vào BATTLE
                retreat = self._find(items, ("rut lui", "thu quan"), x_max=300, y_min=200)
                battle_text = " ".join(text for text, _, _ in items).replace(" ", "")
                if retreat is not None or any(marker in battle_text for marker in ("phongthu", "tancong", "thatbai")):
                    phase = "BATTLE"
                    continue
                self.sleep(self.config.wait_seconds)
                continue

            if phase == "BATTLE":
                point = self._find(items, ("rut lui", "thu quan"), x_max=300, y_min=200)
                battle_text = " ".join(text for text, _, _ in items).replace(" ", "")
                if point is None or not any(marker in battle_text for marker in ("phongthu", "tancong", "thatbai")):
                    self.sleep(self.config.wait_seconds)
                    continue

                casts = 0
                max_casts = 5
                while casts < max_casts:
                    uncast = self._find_uncast_tui_gam(screen, exclude=casted_in_battle)
                    if uncast is None:
                        logger.info("TRANH_BA | không còn túi gấm chưa thả (đã thả %d túi)", casts)
                        break
                    tg_name, tg_x, tg_y = uncast
                    casted_in_battle.add(tg_name)
                    self._cast_tui_gam(tg_name, tg_x, tg_y)
                    casts += 1
                    screen = self.screen_provider()
                    if self._is_battle_ended(screen):
                        phase = "RESULT"
                        result_wait_steps = 0
                        break

                if phase == "RESULT":
                    continue

                logger.info("TRANH_BA | đã thả xong túi gấm -> thực hiện rút lui")
                screen = self.screen_provider()
                items = self._ocr_items(screen)
                retreat_point = self._find(items, ("rut lui", "thu quan"), x_max=300, y_min=200) or point
                self._tap(retreat_point)
                phase = "CONFIRM_RETREAT"
                confirm_wait_steps = 0
                continue

            if phase == "CONFIRM_RETREAT":
                point = self._retreat_confirm(screen)
                if point is None:
                    if self._is_battle_ended(screen):
                        phase = "RESULT"
                        result_wait_steps = 0
                        confirm_wait_steps = 0
                        continue
                    confirm_wait_steps += 1
                    if confirm_wait_steps >= 3:
                        logger.info("TRANH_BA | xác nhận rút lui (fallback 580, 350)")
                        self.input.tap(580, 350)
                        self.sleep(self.config.wait_seconds)
                        phase = "RESULT"
                        result_wait_steps = 0
                        confirm_wait_steps = 0
                        continue
                    self.sleep(self.config.wait_seconds)
                    continue
                self._tap(point)
                phase = "RESULT"
                result_wait_steps = 0
                confirm_wait_steps = 0
                continue

            if phase == "RESULT":
                max_b = total_battles or self.config.battles
                is_last = (battles + 1 >= max_b)
                if not is_last:
                    continue_btn = self._result_continue(screen)
                    if continue_btn is not None:
                        self._tap(continue_btn)
                        battles += 1
                        casted_in_battle.clear()
                        result_wait_steps = 0
                        logger.info("TRANH_BA | hoàn tất trận=%d/%d -> bấm TIẾP TỤC", battles, max_b)
                        phase = "NEXT_BATTLE_WAIT"
                        continue

                    # Các trận trước trận cuối: TUYỆT ĐỐI KHÔNG BẤM QUAY VỀ
                    result_wait_steps += 1
                    if result_wait_steps >= 4:
                        battles += 1
                        casted_in_battle.clear()
                        result_wait_steps = 0
                        logger.info("TRANH_BA | hoàn tất trận=%d/%d -> bấm TIẾP TỤC / TRẬN SAU (fallback 56, 524 và 640, 450)", battles, max_b)
                        self.input.tap(56, 524)
                        self.sleep(0.3)
                        self.input.tap(640, 450)
                        self.sleep(self.config.wait_seconds)
                        phase = "NEXT_BATTLE_WAIT"
                        continue

                    self.sleep(self.config.wait_seconds)
                    continue

                # Chỉ khi đã đến trận cuối (is_last): MỚI BẤM QUAY VỀ
                complete = self._result_complete(screen)
                if complete is not None:
                    self._tap(complete)
                    battles += 1
                    casted_in_battle.clear()
                    result_wait_steps = 0
                    logger.info("TRANH_BA | hoàn tất trận=%d/%d -> bấm QUAY VỀ", battles, max_b)
                    phase = "CLOSE_HOME"
                    continue

                result_wait_steps += 1
                if result_wait_steps >= 4:
                    battles += 1
                    casted_in_battle.clear()
                    result_wait_steps = 0
                    logger.info("TRANH_BA | hoàn tất trận=%d/%d -> bấm QUAY VỀ / HỒI THÀNH (fallback 823, 496 và 320, 450)", battles, max_b)
                    self.input.tap(823, 496)
                    self.sleep(0.3)
                    self.input.tap(320, 450)
                    self.sleep(self.config.wait_seconds)
                    phase = "CLOSE_HOME"
                    continue

                self.sleep(self.config.wait_seconds)
                continue

            if phase == "NEXT_BATTLE_WAIT":
                # 0. Nếu còn màn RESULT (tap chưa ăn)
                continue_btn = self._result_continue(screen)
                if continue_btn is not None:
                    self._tap(continue_btn)
                    continue

                # 1. Đã vào trận BATTLE
                retreat = self._find(items, ("rut lui", "thu quan"), x_max=300, y_min=200)
                battle_text = " ".join(text for text, _, _ in items).replace(" ", "")
                if retreat is not None or any(marker in battle_text for marker in ("phongthu", "tancong", "thatbai")):
                    phase = "BATTLE"
                    continue

                # 2. Ở màn hình Xuất chiến (FORMATION)
                xuat_chien = self._find(items, ("xuat chien",), x_min=600, y_min=350)
                if xuat_chien is not None:
                    self._tap(xuat_chien)
                    phase = "BATTLE"
                    continue

                # 3. Ở màn hình Tranh Bá main panel
                if self._is_main_panel(screen):
                    max_b = total_battles or self.config.battles
                    if battles < max_b:
                        battle_btn = self._find_tb_battle_btn(screen)
                        if battle_btn is not None:
                            self._tap(battle_btn)
                            phase = "BATTLE_OR_FORMATION"
                            continue
                    else:
                        phase = "CLOSE_HOME"
                        continue

                # 4. Nếu hết lượt
                full_text = "".join(text for text, _, _ in items).replace(" ", "")
                if "hetluot" in full_text or "khongconluot" in full_text:
                    logger.info("TRANH_BA | đã hết lượt tranh bá -> về HOME")
                    phase = "CLOSE_HOME"
                    continue

                # 5. Nếu còn màn RESULT (tap chưa ăn)
                continue_btn = self._result_continue(screen)
                if continue_btn is not None:
                    self._tap(continue_btn)
                    continue

                # 6. Nếu về HOME
                if self._is_home(screen):
                    if battles < self.config.battles:
                        phase = "OPEN_HOME_MENU"
                    else:
                        return True
                    continue

                self.sleep(self.config.wait_seconds)
                continue

            if phase == "CLOSE_HOME":
                if not self.recover_home(screen):
                    raise RuntimeError("Tranh Bá: chưa đóng về HOME")
                logger.info("TRANH_BA | hoàn tất, đã về HOME")
                return True

        raise RuntimeError(f"Tranh Bá: vượt quá {self.config.max_steps} bước tại {phase}, trận={battles}")

    def _gt_entry(self, screen):
        match = self._first(screen, self.config.giao_tranh_entry)
        if match is not None:
            return match
        return self._find(
            self._ocr_items(screen), ("giao tranh",),
            x_min=80, x_max=320, y_min=350, y_max=530,
        )

    def _open_gt_entry(self, screen) -> bool:
        entry = self._gt_entry(screen)
        if entry is None:
            military = self._find(
                self._ocr_items(screen), ("quan su",),
                x_max=180, y_min=430,
            )
            if military is not None:
                self._tap(military)
            else:
                self.input.tap(*self.config.military_point)
                self.sleep(self.config.wait_seconds)
            screen = self.screen_provider()
            entry = self._gt_entry(screen)
        if entry is None:
            return False
        point = entry if isinstance(entry, tuple) else (
            entry.x + entry.width // 2, entry.y + entry.height // 2,
        )
        self._tap(point)
        self.sleep(1.2)
        return True

    def _find_uncast_gt_tui_gam(self, screen, exclude: set[str] | None = None) -> tuple[str, int, int] | None:
        exclude = exclude or set()
        best_spec = None
        best_match = None
        best_score_diff = -1.0
        specs = self.config.gt_tui_gam_specs or self.config.tui_gam_specs
        thresh = self.config.gt_tui_gam_threshold or self.config.tui_gam_threshold

        for spec in specs:
            if spec.name in exclude:
                continue
            chua_match = self.vision.find_template(
                screen, f"tui_gam_{spec.name}_chua", spec.chua_tha, thresh,
            ).match
            if not chua_match.found:
                continue

            da_match = self.vision.find_template(
                screen, f"tui_gam_{spec.name}_da", spec.da_tha, thresh,
            ).match

            if not da_match.found or chua_match.confidence > da_match.confidence:
                score_diff = chua_match.confidence - (da_match.confidence if da_match.found else 0.0)
                if score_diff > best_score_diff:
                    best_score_diff = score_diff
                    best_spec = spec
                    best_match = chua_match

        if best_match is not None and best_spec is not None:
            cx = best_match.x + best_match.width // 2
            cy = best_match.y + best_match.height // 2
            return best_spec.name, cx, cy
        return None

    def run_giao_tranh(self, *, start_phase: str = "ENTRY", battles_completed: int = 0) -> bool:
        logger = logging.getLogger("dc3q")
        level = self._get_account_level()
        if level is not None and level < 40:
            logger.info("GIAO_TRANH | cấp=%d < 40 | không cần đánh giao tranh -> bỏ qua", level)
            return True

        target_battles = self.config.gt_battles or self.config.battles or 5
        phase = start_phase
        battles = battles_completed
        reward_wait_steps = 0
        result_wait_steps = 0
        confirm_wait_steps = 0
        casted_in_battle: set[str] = set()

        for _ in range(self.config.max_steps):
            screen = self.screen_provider()
            items = self._ocr_items(screen) if phase != "ENTRY" else []

            if phase == "ENTRY":
                if not self._is_home(screen):
                    raise RuntimeError("Giao Tranh: chưa chứng minh HOME")
                if not self._open_gt_entry(screen):
                    raise RuntimeError("Giao Tranh: HOME/menu Quân sự thiếu control Giao Tranh")
                phase = "FIND_OPPONENT"
                continue

            if phase == "FIND_OPPONENT":
                complete = self._result_complete(screen)
                if complete is not None:
                    self._tap(complete)
                    continue
                if self.config.gt_find_opponent is not None:
                    match_btn = self._match(screen, self.config.gt_find_opponent)
                    if match_btn.found:
                        self._tap(match_btn)
                        phase = "FORMATION"
                        continue
                point = self._find(items, ("tim doi thu",))
                if point is not None:
                    self._tap(point)
                    phase = "FORMATION"
                    continue
                if self._is_home(screen):
                    entry_opened = False
                    for _ in range(3):
                        if self._open_gt_entry(screen):
                            entry_opened = True
                            break
                        self.sleep(self.config.wait_seconds)
                        screen = self.screen_provider()
                    if not entry_opened:
                        raise RuntimeError("Giao Tranh: không mở lại được sau trận trước")
                    continue
                full_text = "".join(text for text, _, _ in items).replace(" ", "")
                if "hetluot" in full_text or "khongconluot" in full_text:
                    logger.info("GIAO_TRANH | đã hết lượt giao tranh; chuyển nhận thưởng")
                    phase = "REWARD"
                    continue
                self.sleep(self.config.wait_seconds)
                continue

            if phase == "FORMATION":
                point = self._find(items, ("xuat chien",), x_min=600, y_min=350)
                if point is None:
                    self.sleep(self.config.wait_seconds)
                    continue
                self._tap(point)
                phase = "BATTLE"
                continue

            if phase == "BATTLE":
                point = self._find(items, ("rut lui", "thu quan"), x_max=300, y_min=200)
                battle_text = " ".join(text for text, _, _ in items).replace(" ", "")
                if point is None or not any(marker in battle_text for marker in ("phongthu", "tancong", "thatbai")):
                    self.sleep(self.config.wait_seconds)
                    continue

                casts = 0
                max_casts = 5
                while casts < max_casts:
                    uncast = self._find_uncast_gt_tui_gam(screen, exclude=casted_in_battle)
                    if uncast is None:
                        logger.info("GIAO_TRANH | không còn túi gấm chưa thả (đã thả %d túi)", casts)
                        break
                    tg_name, tg_x, tg_y = uncast
                    casted_in_battle.add(tg_name)
                    self._cast_tui_gam(tg_name, tg_x, tg_y)
                    casts += 1
                    screen = self.screen_provider()
                    if self._is_battle_ended(screen):
                        phase = "RESULT"
                        result_wait_steps = 0
                        break

                if phase == "RESULT":
                    continue

                logger.info("GIAO_TRANH | đã thả xong túi gấm -> thực hiện rút lui")
                screen = self.screen_provider()
                items = self._ocr_items(screen)
                retreat_point = self._find(items, ("rut lui", "thu quan"), x_max=300, y_min=200) or point
                self._tap(retreat_point)
                phase = "CONFIRM_RETREAT"
                confirm_wait_steps = 0
                continue

            if phase == "CONFIRM_RETREAT":
                point = self._retreat_confirm(screen)
                if point is None:
                    if self._is_battle_ended(screen):
                        phase = "RESULT"
                        result_wait_steps = 0
                        confirm_wait_steps = 0
                        continue
                    confirm_wait_steps += 1
                    if confirm_wait_steps >= 3:
                        logger.info("GIAO_TRANH | xác nhận rút lui (fallback 580, 350)")
                        self.input.tap(580, 350)
                        self.sleep(self.config.wait_seconds)
                        phase = "RESULT"
                        result_wait_steps = 0
                        confirm_wait_steps = 0
                        continue
                    self.sleep(self.config.wait_seconds)
                    continue
                self._tap(point)
                phase = "RESULT"
                result_wait_steps = 0
                confirm_wait_steps = 0
                continue

            if phase == "RESULT":
                is_last = (battles + 1 >= target_battles)
                if not is_last:
                    continue_btn = self._result_continue(screen)
                    if continue_btn is not None:
                        self._tap(continue_btn)
                        battles += 1
                        casted_in_battle.clear()
                        result_wait_steps = 0
                        logger.info("GIAO_TRANH | hoàn tất trận=%d/%d -> bấm TIẾP TỤC", battles, target_battles)
                        phase = "NEXT_BATTLE_WAIT"
                        continue

                    result_wait_steps += 1
                    if result_wait_steps >= 4:
                        battles += 1
                        casted_in_battle.clear()
                        result_wait_steps = 0
                        logger.info("GIAO_TRANH | hoàn tất trận=%d/%d -> bấm TIẾP TỤC / TRẬN SAU (fallback 56, 524 và 640, 450)", battles, target_battles)
                        self.input.tap(56, 524)
                        self.sleep(0.3)
                        self.input.tap(640, 450)
                        self.sleep(self.config.wait_seconds)
                        phase = "NEXT_BATTLE_WAIT"
                        continue

                    self.sleep(self.config.wait_seconds)
                    continue

                complete = self._result_complete(screen)
                if complete is not None:
                    self._tap(complete)
                    battles += 1
                    casted_in_battle.clear()
                    result_wait_steps = 0
                    logger.info("GIAO_TRANH | hoàn tất trận=%d/%d -> bấm QUAY VỀ", battles, target_battles)
                    phase = "REWARD"
                    continue

                result_wait_steps += 1
                if result_wait_steps >= 4:
                    battles += 1
                    casted_in_battle.clear()
                    result_wait_steps = 0
                    logger.info("GIAO_TRANH | hoàn tất trận=%d/%d -> bấm QUAY VỀ / HỒI THÀNH (fallback 823, 496 và 320, 450)", battles, target_battles)
                    self.input.tap(823, 496)
                    self.sleep(0.3)
                    self.input.tap(320, 450)
                    self.sleep(self.config.wait_seconds)
                    phase = "REWARD"
                    continue

                self.sleep(self.config.wait_seconds)
                continue

            if phase == "NEXT_BATTLE_WAIT":
                continue_btn = self._result_continue(screen)
                if continue_btn is not None:
                    self._tap(continue_btn)
                    continue

                retreat = self._find(items, ("rut lui", "thu quan"), x_max=300, y_min=200)
                battle_text = " ".join(text for text, _, _ in items).replace(" ", "")
                if retreat is not None or any(marker in battle_text for marker in ("phongthu", "tancong", "thatbai")):
                    phase = "BATTLE"
                    continue

                xuat_chien = self._find(items, ("xuat chien",), x_min=600, y_min=350)
                if xuat_chien is not None:
                    self._tap(xuat_chien)
                    phase = "BATTLE"
                    continue

                tim_doi_thu = self._find(items, ("tim doi thu",))
                if tim_doi_thu is not None:
                    self._tap(tim_doi_thu)
                    phase = "FORMATION"
                    continue

                full_text = "".join(text for text, _, _ in items).replace(" ", "")
                if "hetluot" in full_text or "khongconluot" in full_text:
                    logger.info("GIAO_TRANH | đã hết lượt giao tranh; chuyển nhận thưởng")
                    phase = "REWARD"
                    continue

                if self._is_home(screen):
                    if battles < target_battles:
                        phase = "FIND_OPPONENT"
                    else:
                        phase = "HOME"
                    continue

                self.sleep(self.config.wait_seconds)
                continue

            if phase == "REWARD":
                if self._dismiss_exit_popup(screen):
                    continue
                if self._is_home(screen):
                    logger.info("GIAO_TRANH | đủ %d trận, đã ở HOME", battles)
                    return True
                point = self._find(items, ("da ro", "tro ve", "trdve"), x_min=250, y_min=300)
                if point is not None:
                    self._tap(point)
                    phase = "HOME"
                    continue
                complete = self._result_complete(screen)
                if complete is not None:
                    self._tap(complete)
                    phase = "HOME"
                    continue
                hoi_thanh = self._find(items, ("hoi thanh", "hoithanh"), y_min=400)
                if hoi_thanh is not None:
                    self._tap(hoi_thanh)
                    phase = "HOME"
                    continue
                close_btn = self._find(items, ("tro ve", "dong", "thoat"), y_max=150)
                if close_btn is not None:
                    self._tap(close_btn)
                    continue
                reward_wait_steps += 1
                if reward_wait_steps >= 3:
                    logger.info("GIAO_TRANH | không có popup thưởng tại REWARD; quay về HOME bằng Hồi thành")
                    self.input.tap(820, 495)
                    self.sleep(self.config.wait_seconds)
                    if self._is_home(self.screen_provider()):
                        return True
                    phase = "HOME"
                    continue
                self.sleep(self.config.wait_seconds)
                continue

            if phase == "HOME":
                if self._dismiss_exit_popup(screen):
                    continue
                if self._is_home(screen):
                    logger.info("GIAO_TRANH | đủ %d trận, thưởng đã đóng, HOME", battles)
                    if self._first(screen, self.config.tranh_ba_entry) is not None:
                        self.input.tap(*self.config.military_close_point)
                        self.sleep(self.config.wait_seconds)
                    return True
                complete = self._result_complete(screen)
                if complete is not None:
                    self._tap(complete)
                    continue
                hoi_thanh = self._find(items, ("hoi thanh", "hoithanh"), y_min=400)
                if hoi_thanh is not None:
                    self._tap(hoi_thanh)
                    self.sleep(self.config.wait_seconds)
                    continue
                close_btn = self._find(items, ("tro ve", "dong", "thoat"), y_max=150)
                if close_btn is not None:
                    self._tap(close_btn)
                    self.sleep(self.config.wait_seconds)
                    continue
                self.input.tap(820, 495)
                self.sleep(self.config.wait_seconds)
                screen = self.screen_provider()
                if self._is_home(screen):
                    return True
                continue

        raise RuntimeError(f"Giao Tranh: vượt quá {self.config.max_steps} bước tại {phase}, trận={battles}")

    def run(self) -> bool:
        self.run_tranh_ba()
        self.recover_home()
        self.run_giao_tranh()
        return self.recover_home()


class QuanSuRuntimeStep:
    """Expose one Quân Sự sub-activity (Tranh_Ba, Giao_Tranh) as a resumable runtime task."""

    def __init__(self, runner: QuanSuRunner, runtime_task: str, method: str):
        self.runner = runner
        self.runtime_task = runtime_task
        self.method = method
        self.soft_errors: list[str] = []

    def run(self) -> bool:
        self.soft_errors = []
        if self.method == "run_giao_tranh":
            level = self.runner._get_account_level()
            if level is not None and level < 40:
                logging.getLogger("dc3q").info("GIAO_TRANH | cấp=%d < 40 | không cần đánh giao tranh -> bỏ qua", level)
                return True
        res = getattr(self.runner, self.method)()
        if not self.runner.recover_home():
            raise RuntimeError(f"{self.runtime_task}: không recover được HOME")
        return res if res is not None else True

    def recover_home(self) -> bool:
        return self.runner.recover_home()

