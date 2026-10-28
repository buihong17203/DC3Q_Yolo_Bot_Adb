import pytest
from unittest.mock import MagicMock
from app.vision.detector import VisionDetector, Detection
from app.vision.yolo import YoloDetection


def test_vision_detector_yolo_lazy_load():
    detector = VisionDetector()
    assert detector.yolo is None

    mock_yolo = MagicMock()
    mock_yolo.is_loaded = True
    mock_yolo.predict.return_value = [
        YoloDetection(class_id=3, label="button", confidence=0.91, x1=10, y1=20, x2=50, y2=80)
    ]
    mock_yolo.find_by_label.return_value = [
        YoloDetection(class_id=3, label="button", confidence=0.91, x1=10, y1=20, x2=50, y2=80)
    ]
    mock_yolo.find_first.return_value = YoloDetection(
        class_id=3, label="button", confidence=0.91, x1=10, y1=20, x2=50, y2=80
    )

    detector.yolo = mock_yolo

    # find_objects (all)
    dets = detector.find_objects("fake_screen")
    assert len(dets) == 1
    assert dets[0].label == "button"

    # find_objects (filtered by label)
    btns = detector.find_objects("fake_screen", label="button")
    assert len(btns) == 1

    # find_first_object
    first_btn = detector.find_first_object("fake_screen", label="button")
    assert first_btn is not None
    assert first_btn.center == (30, 50)
