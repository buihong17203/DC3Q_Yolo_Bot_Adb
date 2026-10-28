import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
from app.state.scene import SceneClassifier
from app.vision.ocr import get_ocr_engine

temp_dir = PROJECT_ROOT / "temp"
temp_dir.mkdir(parents=True, exist_ok=True)
img_path = temp_dir / "screen_now.png"

if not img_path.exists():
    print(f"File not found: {img_path}")
    sys.exit(1)

img = cv2.imread(str(img_path))
sc = SceneClassifier()
scene_res = sc.classify(img)

ocr = get_ocr_engine()
ocr_res, _ = ocr(img)

output_path = temp_dir / "screen_now_info.txt"
with open(output_path, "w", encoding="utf-8") as f:
    f.write(f"Scene: {scene_res.scene.value} ({scene_res.detail})\n")
    f.write("OCR:\n")
    for r in (ocr_res or []):
        f.write(f"  {r[1]} -> {r[0]}\n")

print(f"Done: {output_path}")
