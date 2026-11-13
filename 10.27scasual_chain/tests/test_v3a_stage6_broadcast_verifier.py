import numpy as np
import pytest

from story_video_agent_v3.stage6_broadcast_verifier import _distance, _hash_frame


def test_identical_image_phash_distance_zero():
    a = np.zeros((120, 200, 3), dtype=np.uint8)
    a[15:75, 30:130] = (255, 255, 255)
    assert _distance(_hash_frame(a), _hash_frame(a.copy())) == 0


def test_phash_is_64_bit_and_distance_is_symmetric():
    a = np.zeros((120, 200, 3), dtype=np.uint8)
    b = a.copy()
    a[10:40, 10:50] = (255, 255, 255)
    b[70:110, 120:190] = (255, 255, 255)
    ha, hb = _hash_frame(a), _hash_frame(b)
    assert 0 <= ha < 2**64 and 0 <= hb < 2**64
    assert _distance(ha, hb) == _distance(hb, ha)


def test_phash_rejects_grayscale_input_without_silent_guess():
    with pytest.raises(Exception):
        _hash_frame(np.zeros((10, 10), dtype=np.uint8))
