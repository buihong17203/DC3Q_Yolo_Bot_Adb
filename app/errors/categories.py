from __future__ import annotations

from enum import Enum, auto


class ErrorCategory(Enum):
    """Phân loại nhóm lỗi trong hệ thống DC3Q Bot."""
    ADB_CONNECTION = auto()   # Mất kết nối thiết bị, server ADB chết
    APP_CRASH_ANR = auto()    # Game văng, crash, ANR (không phản hồi)
    ACCOUNT_AUTH = auto()     # Sai pass, server từ chối, kẹt form đăng nhập
    UI_STUCK_POPUP = auto()   # Kẹt giao diện, popup che khuất, không về được HOME
    TASK_FAILURE = auto()     # Lỗi khi thực hiện một nhiệm vụ cụ thể
    VISION_CAPTURE = auto()   # Lỗi chụp ảnh màn hình, ảnh đen/rỗng
    SYSTEM_FATAL = auto()     # Ngoại lệ hệ thống nghiêm trọng


class ErrorSeverity(Enum):
    """Mức độ nghiêm trọng của lỗi."""
    LOW = "LOW"             # Có thể thử lại ngay lập tức
    MEDIUM = "MEDIUM"       # Bỏ qua task hiện tại, tiếp tục task khác
    HIGH = "HIGH"           # Bỏ qua account hiện tại, phục hồi & chuyển acc kế
    CRITICAL = "CRITICAL"   # Cần can thiệp thiết bị hoặc dừng luồng
