from __future__ import annotations

import cv2
import numpy as np

from app.vision import TemplateMatcher


def test_template_matcher_finds_synthetic_target() -> None:
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    # A non-uniform pattern avoids degenerate normalized template matching.
    template = np.zeros((20, 30, 3), dtype=np.uint8)
    cv2.rectangle(template, (2, 2), (27, 17), (255, 255, 255), 2)
    cv2.line(template, (0, 0), (29, 19), (127, 127, 127), 1)
    image[50:70, 80:110] = template

    matcher = TemplateMatcher(default_threshold=0.99, grayscale=True)
    match = matcher.find_best(image, template)

    assert match is not None
    assert match.bbox == (80, 50, 110, 70)
    assert match.center == (95, 60)
