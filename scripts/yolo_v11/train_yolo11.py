"""Script hỗ trợ huấn luyện (Fine-tune) mô hình YOLO11 cho game DC3Q.
Cách dùng:
    python scripts/yolo_v11/train_yolo11.py --epochs 30 --batch 8 --imgsz 640
"""

from __future__ import annotations
import argparse
import sys
import shutil
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def main():
    parser = argparse.ArgumentParser(description="Huấn luyện mô hình YOLO11 cho DC3Q")
    parser.add_argument("--data", type=str, default="data/img/templates/trainning_yolo/dataset.yaml", help="File cấu hình dataset YAML")
    parser.add_argument("--model", type=str, default="data/img/yolo/yolo11n.pt", help="Trọng số khởi tạo (yolo11n.pt)")
    parser.add_argument("--epochs", type=int, default=30, help="Số epoch huấn luyện")
    parser.add_argument("--batch", type=int, default=8, help="Batch size")
    parser.add_argument("--imgsz", type=int, default=640, help="Kích thước ảnh (640 hoặc 416)")
    parser.add_argument("--device", type=str, default="cpu", help="Device: 'cpu', '0' (GPU CUDA), '' (auto)")
    parser.add_argument("--project", type=str, default="data/img/yolo/runs", help="Thư mục xuất kết quả")
    parser.add_argument("--name", type=str, default="dc3q_yolo11", help="Tên phiên train")
    parser.add_argument("--freeze", type=int, default=None, help="Số layer backbone cần đóng băng để train nhanh trên CPU (ví dụ: 10)")
    parser.add_argument("--export-onnx", action="store_true", default=True, help="Tự động xuất sang ONNX runtime sau khi train")
    args = parser.parse_args()

    data_path = PROJECT_ROOT / args.data if not Path(args.data).is_absolute() else Path(args.data)
    model_path = PROJECT_ROOT / args.model if not Path(args.model).is_absolute() else Path(args.model)

    if not data_path.exists():
        print(f"[!] Lỗi: Không tìm thấy file cấu hình dataset tại '{data_path}'")
        sys.exit(1)

    try:
        from ultralytics import YOLO
    except ImportError:
        print("[!] Lỗi: Cần cài đặt ultralytics: pip install ultralytics")
        sys.exit(1)

    print(f"[*] Bắt đầu huấn luyện YOLO11...")
    print(f"    - Base Model : {model_path}")
    print(f"    - Dataset    : {data_path}")
    print(f"    - Epochs     : {args.epochs}")
    print(f"    - Imgsz      : {args.imgsz}")
    print(f"    - Batch      : {args.batch}")
    print(f"    - Device     : {args.device}")

    model = YOLO(str(model_path))
    results = model.train(
        data=str(data_path),
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        device=args.device if args.device else None,
        freeze=args.freeze,
        project=str(PROJECT_ROOT / args.project),
        name=args.name,
        exist_ok=True,
    )
    save_dir = Path(results.save_dir)
    print(f"[OK] Huấn luyện hoàn tất! Kết quả được lưu tại: {save_dir}")

    best_pt = save_dir / "weights" / "best.pt"
    if best_pt.exists():
        dst_pt = PROJECT_ROOT / "data" / "img" / "yolo" / "dc3q_yolo11_best.pt"
        shutil.copy2(best_pt, dst_pt)
        print(f"[OK] Đã cập nhật mô hình tốt nhất vào: {dst_pt}")

        if args.export_onnx:
            print("[*] Đang xuất mô hình sang ONNX runtime để tối ưu tốc độ CPU...")
            try:
                best_model = YOLO(str(dst_pt))
                onnx_path = best_model.export(format="onnx", imgsz=args.imgsz)
                dst_onnx = PROJECT_ROOT / "data" / "img" / "yolo" / "dc3q_yolo11_best.onnx"
                if Path(onnx_path) != dst_onnx and Path(onnx_path).exists():
                    shutil.copy2(onnx_path, dst_onnx)
                print(f"[OK] Đã xuất mô hình ONNX thành công: {dst_onnx}")
            except Exception as e:
                print(f"[!] Xuất ONNX thất bại: {e}")


if __name__ == "__main__":
    main()
