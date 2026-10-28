"""Script kiểm tra hoạt động của mô hình YOLO11 trong dự án DC3Q.
Cách dùng:
    python scripts/check_yolo11.py
    python scripts/check_yolo11.py --image path/to/screenshot.png
"""

from __future__ import annotations
import argparse
import sys
import time
from pathlib import Path
import numpy as np

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Đảm bảo đường dẫn gốc của dự án có trong sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.vision.yolo import YoloDetector, DEFAULT_MODEL_PATH, resolve_default_yolo_model


def main():
    default_model = resolve_default_yolo_model() or DEFAULT_MODEL_PATH
    parser = argparse.ArgumentParser(description="Kiểm tra YOLO11 trên ảnh game hoặc frame giả lập")
    parser.add_argument("--model", type=str, default=str(default_model), help="Đường dẫn file .pt")
    parser.add_argument("--image", type=str, default=None, help="Đường dẫn file ảnh để nhận diện")
    parser.add_argument("--conf", type=float, default=0.25, help="Ngưỡng confidence (mặc định: 0.25)")
    args = parser.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        print(f"[!] Lỗi: Không tìm thấy file model tại '{model_path}'")
        sys.exit(1)

    print(f"[*] Khởi tạo YOLO11 Detector với model: {model_path}...")
    detector = YoloDetector(model_path=model_path)
    start_load = time.perf_counter()
    detector.load()
    load_time = time.perf_counter() - start_load
    print(f"[OK] Nạp mô hình thành công trong {load_time:.2f}s!")

    # Chuẩn bị ảnh đầu vào
    if args.image and Path(args.image).is_file():
        from PIL import Image
        print(f"[*] Đang nhận diện trên ảnh: {args.image}")
        img = Image.open(args.image).convert("RGB")
    else:
        sample_images = list((PROJECT_ROOT / "data" / "img").rglob("*.png"))
        if sample_images:
            sample_img_path = sample_images[0]
            from PIL import Image
            print(f"[*] Thử nghiệm trên ảnh mẫu có sẵn: {sample_img_path.relative_to(PROJECT_ROOT)}")
            img = Image.open(sample_img_path).convert("RGB")
        else:
            print("[*] Tạo ảnh RGB mẫu 1280x720 để kiểm tra tốc độ suy luận...")
            img = np.zeros((720, 1280, 3), dtype=np.uint8)

    # Chạy suy luận
    print("[*] Đang thực thi suy luận...")
    t0 = time.perf_counter()
    detections = detector.predict(img, confidence=args.conf)
    infer_time = (time.perf_counter() - t0) * 1000

    print(f"[OK] Hoàn thành suy luận trong {infer_time:.1f}ms! Tìm thấy {len(detections)} đối tượng:")
    for i, det in enumerate(detections, 1):
        cx, cy = det.center
        print(f"    {i}. [{det.label}] (conf: {det.confidence:.2f}) -> Box: {det.box}, Center: ({cx}, {cy})")


if __name__ == "__main__":
    main()
