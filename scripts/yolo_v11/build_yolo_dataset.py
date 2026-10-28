"""Build YOLOv11 Dataset for DC3Q Bot via Template Matching Auto-Annotation.
Tự động gom toàn bộ ảnh, đối chiếu mẫu (template matching) để gán nhãn bounding-box chuẩn YOLO.

Xuất ra:
    D:\\Antigravity_Data\\DC3Q_Yolo_Bot_Adb - 01\\data\\img\\templates\\trainning_yolo\\
    ├── dataset.yaml
    ├── images/
    │   ├── train/
    │   ├── val/
    │   └── all/
    ├── labels/
    │   ├── train/
    │   ├── val/
    │   └── all/
    └── templates/  (bản sao toàn bộ ảnh template con)
"""

from __future__ import annotations
import os
import sys
import shutil
import random
from pathlib import Path
from dataclasses import dataclass
import cv2
import numpy as np

# Đảm bảo UTF-8 & Unbuffered output
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = WORKSPACE_ROOT / "data" / "img" / "templates" / "trainning_yolo"

CLASSES = {
    0: "monster",
    1: "reward",
    2: "npc",
    3: "button",
    4: "item",
    5: "popup_close",
}


def log(msg: str):
    print(msg, flush=True)


def classify_template(name: str) -> tuple[int, str]:
    """Phân loại class ID dựa trên tên file template."""
    n = name.lower()
    # 5: popup_close (nút đóng, thoát, bấm ngoài màn hình để tắt)
    if any(k in n for k in ["dong", "close", "cancel", "thoat", "anvaochotrong", "anmanhinh", "x_dong", "quaylai", "return"]):
        return 5, "popup_close"
    # 1: reward (chúc mừng nhận được, phần thưởng, lì xì, phúc lợi, rương)
    if any(k in n for k in ["thuong", "reward", "chucmung", "lixi", "phucloi", "quatang", "ruong", "diemdanh", "qua_"]):
        return 1, "reward"
    # 4: item (vật phẩm, ngọc, kim cương, vàng, bạc, thẻ, giá)
    if any(k in n for k in ["item", "ngoc", "knb", "vang", "bac", "manh", "vatpham", "da_", "ruou", "the_", "price", "exp"]):
        return 4, "item"
    # 0: monster (quái, boss, địch quân tập kích)
    if any(k in n for k in ["quai", "boss", "monster", "dichquan", "tapkich"]):
        return 0, "monster"
    # 2: npc (nhân vật, tướng, quân sư)
    if any(k in n for k in ["npc", "tuong_", "quansu_", "nhanvat"]):
        return 2, "npc"
    # 3: button (nút bấm, tab, menu, chọn...)
    return 3, "button"


@dataclass
class TemplateInfo:
    path: Path
    name: str
    class_id: int
    class_name: str
    gray: np.ndarray
    h: int
    w: int
    parent_dir: Path


def nms(boxes: list[dict], iou_thresh: float = 0.45) -> list[dict]:
    """Non-Maximum Suppression loại bỏ các bounding box trùng lặp."""
    if not boxes:
        return []
    boxes = sorted(boxes, key=lambda b: b["score"], reverse=True)
    kept: list[dict] = []
    for b in boxes:
        overlap = False
        for k in kept:
            ix1 = max(b["x1"], k["x1"])
            iy1 = max(b["y1"], k["y1"])
            ix2 = min(b["x2"], k["x2"])
            iy2 = min(b["y2"], k["y2"])
            iw = max(0, ix2 - ix1)
            ih = max(0, iy2 - iy1)
            inter = iw * ih
            area1 = (b["x2"] - b["x1"]) * (b["y2"] - b["y1"])
            area2 = (k["x2"] - k["x1"]) * (k["y2"] - k["y1"])
            union = area1 + area2 - inter
            if union > 0 and (inter / union) > iou_thresh:
                overlap = True
                break
        if not overlap:
            kept.append(b)
    return kept


def build_dataset():
    log(f"[*] Bắt đầu xây dựng Dataset YOLOv11 tại: {OUTPUT_DIR}")

    images_dir = OUTPUT_DIR / "images"
    labels_dir = OUTPUT_DIR / "labels"
    all_img_dir = images_dir / "all"
    all_lbl_dir = labels_dir / "all"
    train_img_dir = images_dir / "train"
    train_lbl_dir = labels_dir / "train"
    val_img_dir = images_dir / "val"
    val_lbl_dir = labels_dir / "val"
    templates_copy_dir = OUTPUT_DIR / "templates"

    for d in [all_img_dir, all_lbl_dir, train_img_dir, train_lbl_dir, val_img_dir, val_lbl_dir, templates_copy_dir]:
        d.mkdir(parents=True, exist_ok=True)

    templates_root = WORKSPACE_ROOT / "data" / "img" / "templates"
    item_root = WORKSPACE_ROOT / "data" / "img" / "item"

    # 1. Nạp và phân loại tất cả template con
    log("[1/5] Đang nạp tất cả template con và tối ưu grayscale...")
    all_templates: list[TemplateInfo] = []
    templates_by_parent: dict[Path, list[TemplateInfo]] = {}
    global_close_templates: list[TemplateInfo] = []
    global_item_templates: list[TemplateInfo] = []
    global_home_templates: list[TemplateInfo] = []

    for p in templates_root.rglob("*"):
        if p.suffix.lower() not in (".png", ".jpg"):
            continue
        if "full screen" in str(p).lower() or "full-screen" in str(p).lower():
            continue
        if "trainning_yolo" in str(p).lower():
            continue

        gray = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        h, w = gray.shape
        if h > 450 and w > 600:
            continue

        cid, cname = classify_template(p.name)
        parent_dir = p.parent
        t_info = TemplateInfo(
            path=p,
            name=p.name,
            class_id=cid,
            class_name=cname,
            gray=gray,
            h=h,
            w=w,
            parent_dir=parent_dir,
        )
        all_templates.append(t_info)
        templates_by_parent.setdefault(parent_dir, []).append(t_info)

        if cid == 5:
            global_close_templates.append(t_info)
        if "stars/home" in str(parent_dir).replace("\\", "/").lower():
            global_home_templates.append(t_info)

    if item_root.exists():
        for p in item_root.glob("*.png"):
            gray = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
            if gray is not None:
                h, w = gray.shape
                t_info = TemplateInfo(
                    path=p,
                    name=p.name,
                    class_id=4,
                    class_name="item",
                    gray=gray,
                    h=h,
                    w=w,
                    parent_dir=item_root,
                )
                all_templates.append(t_info)
                global_item_templates.append(t_info)

    log(f"      -> Đã nạp {len(all_templates)} templates.")

    # 2. Sao chép toàn bộ template vào thư mục templates_copy_dir
    log("[2/5] Sao chép toàn bộ ảnh template vào trainning_yolo/templates/...")
    copied_templates = 0
    for tpl in all_templates:
        dest_p = templates_copy_dir / tpl.name
        if not dest_p.exists():
            shutil.copy2(tpl.path, dest_p)
            copied_templates += 1
    log(f"      -> Đã sao chép {copied_templates} templates.")

    # 3. Thu thập tất cả ảnh full-screen
    log("[3/5] Thu thập các ảnh full-screen từ dự án...")
    fs_files: list[Path] = []
    for p in templates_root.rglob("*"):
        if p.suffix.lower() in (".png", ".jpg") and ("full screen" in str(p).lower() or "full-screen" in str(p).lower()):
            if "trainning_yolo" not in str(p).lower():
                fs_files.append(p)
    log(f"      -> Tìm thấy {len(fs_files)} ảnh full-screen.")

    # 4. Gán nhãn tự động
    log("[4/5] Đang thực hiện Auto-Annotation qua Template Matching...")
    total_boxes = 0
    annotated_samples: list[tuple[str, Path, list[dict]]] = []
    class_counts = {cid: 0 for cid in CLASSES}

    for idx, fs_path in enumerate(fs_files, 1):
        rel = fs_path.relative_to(templates_root)
        cat_slug = str(rel.parent).replace("\\", "_").replace("/", "_").replace(" ", "_")
        unique_name = f"{cat_slug}__{fs_path.name}"

        fs_bgr = cv2.imread(str(fs_path))
        if fs_bgr is None:
            continue
        fh, fw = fs_bgr.shape[:2]
        fs_gray = cv2.cvtColor(fs_bgr, cv2.COLOR_BGR2GRAY)

        # Tìm các template anh em (sibling) cùng mục tính năng
        feature_root = fs_path.parent.parent
        sibling_candidates: list[TemplateInfo] = []
        for p_dir, t_list in templates_by_parent.items():
            if str(p_dir).startswith(str(feature_root)):
                sibling_candidates.extend(t_list)

        # Danh sách ứng viên: Sibling (thresh 0.85) + Global Close (0.88) + Items (0.90)
        candidates: list[tuple[TemplateInfo, float]] = []
        for tpl in sibling_candidates:
            candidates.append((tpl, 0.85))
        for tpl in global_close_templates[:15]:
            if tpl not in sibling_candidates:
                candidates.append((tpl, 0.88))
        for tpl in global_item_templates[:10]:
            if tpl not in sibling_candidates:
                candidates.append((tpl, 0.90))

        raw_boxes: list[dict] = []
        for tpl, thresh in candidates:
            th, tw = tpl.h, tpl.w
            if th >= fh or tw >= fw:
                continue

            res = cv2.matchTemplate(fs_gray, tpl.gray, cv2.TM_CCOEFF_NORMED)
            for _ in range(3):
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val < thresh:
                    break
                gx, gy = max_loc
                raw_boxes.append({
                    "class_id": tpl.class_id,
                    "class_name": tpl.class_name,
                    "x1": gx,
                    "y1": gy,
                    "x2": gx + tw,
                    "y2": gy + th,
                    "score": float(max_val),
                    "template": tpl.name,
                })
                # Mask out vùng lân cận
                my1 = max(0, gy - th // 2)
                my2 = min(fh, gy + th // 2 + 1)
                mx1 = max(0, gx - tw // 2)
                mx2 = min(fw, gx + tw // 2 + 1)
                res[my1:my2, mx1:mx2] = 0.0

        boxes = nms(raw_boxes, iou_thresh=0.45)
        total_boxes += len(boxes)
        for b in boxes:
            class_counts[b["class_id"]] = class_counts.get(b["class_id"], 0) + 1
        annotated_samples.append((unique_name, fs_path, boxes))

        # Lưu ảnh vào all_img_dir
        dest_img_path = all_img_dir / unique_name
        shutil.copy2(fs_path, dest_img_path)

        # Lưu nhãn vào all_lbl_dir
        lbl_name = Path(unique_name).stem + ".txt"
        lbl_path = all_lbl_dir / lbl_name
        with open(lbl_path, "w", encoding="utf-8") as f:
            for b in boxes:
                cx = ((b["x1"] + b["x2"]) / 2.0) / fw
                cy = ((b["y1"] + b["y2"]) / 2.0) / fh
                bw = (b["x2"] - b["x1"]) / fw
                bh = (b["y2"] - b["y1"]) / fh
                f.write(f"{b['class_id']} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")

        if idx % 25 == 0 or idx == len(fs_files):
            log(f"      -> Tiến độ: {idx}/{len(fs_files)} ảnh ({total_boxes} nhãn bounding-box)...")

    # 5. Phân chia Train (80%) / Val (20%)
    log("[5/5] Phân chia tập dữ liệu: 80% Train, 20% Val...")
    random.seed(42)
    shuffled = list(annotated_samples)
    random.shuffle(shuffled)
    split_idx = int(len(shuffled) * 0.8)
    train_set = shuffled[:split_idx]
    val_set = shuffled[split_idx:]

    for unique_name, _, _ in train_set:
        shutil.copy2(all_img_dir / unique_name, train_img_dir / unique_name)
        lbl_name = Path(unique_name).stem + ".txt"
        shutil.copy2(all_lbl_dir / lbl_name, train_lbl_dir / lbl_name)

    for unique_name, _, _ in val_set:
        shutil.copy2(all_img_dir / unique_name, val_img_dir / unique_name)
        lbl_name = Path(unique_name).stem + ".txt"
        shutil.copy2(all_lbl_dir / lbl_name, val_lbl_dir / lbl_name)

    # dataset.yaml
    dataset_yaml_path = OUTPUT_DIR / "dataset.yaml"
    yaml_content = f"""# DC3Q Auto-Annotated YOLOv11 Dataset
path: {OUTPUT_DIR.as_posix()}
train: images/train
val: images/val

names:
  0: monster
  1: reward
  2: npc
  3: button
  4: item
  5: popup_close
"""
    dataset_yaml_path.write_text(yaml_content, encoding="utf-8")

    # Cập nhật cấu hình mặc định data/img/yolo/classes.yaml
    (WORKSPACE_ROOT / "data" / "img" / "yolo" / "classes.yaml").write_text(yaml_content, encoding="utf-8")

    log("\n" + "=" * 60)
    log("HOÀN TẤT XÂY DỰNG DATASET YOLOV11!")
    log(f"- Thư mục đích         : {OUTPUT_DIR}")
    log(f"- Tổng số ảnh màn hình : {len(annotated_samples)}")
    log(f"- Tổng số bounding-box : {total_boxes} nhãn")
    log(f"- Phân phối class      : {class_counts}")
    log(f"- Tập Train            : {len(train_set)} ảnh ({train_img_dir})")
    log(f"- Tập Val              : {len(val_set)} ảnh ({val_img_dir})")
    log(f"- Templates con đã copy: {copied_templates} ảnh ({templates_copy_dir})")
    log(f"- File cấu hình YOLO   : {dataset_yaml_path}")
    log("=" * 60)


if __name__ == "__main__":
    build_dataset()
