import pytest
from pathlib import Path
from unittest.mock import MagicMock
from app.vision.yolo import YoloDetection, YoloDetector, DEFAULT_MODEL_PATH


def test_yolo_detection_properties():
    det = YoloDetection(class_id=3, label="button", confidence=0.92, x1=100.0, y1=200.0, x2=200.0, y2=250.0)
    assert det.width == 100.0
    assert det.height == 50.0
    assert det.center_x == 150.0
    assert det.center_y == 225.0
    assert det.center == (150, 225)
    assert det.box == (100, 200, 200, 250)


def test_yolo_detector_not_loaded_raises():
    detector = YoloDetector(model_path="non_existent.pt")
    assert not detector.is_loaded
    with pytest.raises(RuntimeError, match="YOLO model chưa load"):
        detector.predict("dummy_image")


def test_yolo_detector_mock_predict():
    detector = YoloDetector()
    mock_model = MagicMock()

    class FakeBox:
        def __init__(self, xyxy, cls, conf):
            self.xyxy = [xyxy]
            self.cls = [cls]
            self.conf = [conf]

    class FakeResult:
        def __init__(self):
            self.names = {0: "monster", 3: "button"}
            self.boxes = [
                FakeBox([10, 20, 50, 80], 0, 0.88),
                FakeBox([100, 200, 150, 250], 3, 0.95),
            ]

    mock_model.predict.return_value = [FakeResult()]
    detector.model = mock_model
    assert detector.is_loaded

    dets = detector.predict("fake_img", confidence=0.5)
    assert len(dets) == 2
    assert dets[0].label == "monster"
    assert dets[0].confidence == 0.88
    assert dets[1].label == "button"
    assert dets[1].center == (125, 225)

    # find_by_label
    btns = detector.find_by_label("fake_img", "button")
    assert len(btns) == 1
    assert btns[0].label == "button"

    # find_first
    btn = detector.find_first("fake_img", "button")
    assert btn is not None
    assert btn.class_id == 3

    missing = detector.find_first("fake_img", "non_existing_label")
    assert missing is None


def test_default_model_path_exists():
    assert DEFAULT_MODEL_PATH.exists(), f"Default YOLO11 model path '{DEFAULT_MODEL_PATH}' should exist."
