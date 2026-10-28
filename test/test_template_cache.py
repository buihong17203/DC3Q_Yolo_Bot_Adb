import numpy as np
import cv2
from app.vision.template import TemplateMatcher

def test_template_matcher_in_memory_and_resize_cache(tmp_path):
    matcher = TemplateMatcher()
    matcher.clear_cache()

    # Create dummy screen (540x960) with noise/texture
    np.random.seed(42)
    screen = np.random.randint(0, 100, (540, 960, 3), dtype=np.uint8)

    # Distinct pattern 50x50 at (200, 150)
    pattern = np.zeros((50, 50, 3), dtype=np.uint8)
    pattern[:25, :25] = 255
    pattern[25:, 25:] = 200

    screen[150:200, 200:250] = pattern

    # Save template
    tpl_path = tmp_path / "test_icon.png"
    cv2.imwrite(str(tpl_path), pattern)

    # 1. Test exact matching with in-memory caching
    match = matcher.match(screen, tpl_path, threshold=0.80)
    assert match.found
    assert abs(match.x - 200) <= 2
    assert abs(match.y - 150) <= 2

    # Verify template is in _template_cache
    assert str(tpl_path.resolve()) in TemplateMatcher._template_cache

    # 2. Test multi-scale matching and resize cache
    scaled_pattern = cv2.resize(pattern, (60, 60), interpolation=cv2.INTER_NEAREST)
    scaled_screen = np.random.randint(0, 100, (540, 960, 3), dtype=np.uint8)
    scaled_screen[150:210, 200:260] = scaled_pattern

    # Match with scale 1.2
    match_scaled = matcher.match(scaled_screen, tpl_path, threshold=0.75, scales=[1.2])
    assert match_scaled.found
    assert abs(match_scaled.x - 200) <= 2
    assert abs(match_scaled.y - 150) <= 2
    assert match_scaled.width == 60 and match_scaled.height == 60

    # Verify that the resized version was cached in _resized_cache
    cache_keys = list(TemplateMatcher._resized_cache.keys())
    assert any(k[1] == 60 and k[2] == 60 for k in cache_keys), f"Resized cache missing key: {cache_keys}"

    # 3. Test clear_cache
    matcher.clear_cache()
    assert len(TemplateMatcher._template_cache) == 0
    assert len(TemplateMatcher._resized_cache) == 0
