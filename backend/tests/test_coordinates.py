import pytest

from src.services.coordinates import gcj02_to_wgs84, wgs84_to_gcj02


def test_shanghai_coordinate_round_trip():
    wgs_lat, wgs_lng = 31.2304, 121.4737

    gcj_lat, gcj_lng = wgs84_to_gcj02(wgs_lat, wgs_lng)
    restored_lat, restored_lng = gcj02_to_wgs84(gcj_lat, gcj_lng)

    assert abs(gcj_lat - wgs_lat) > 0.001
    assert abs(gcj_lng - wgs_lng) > 0.001
    assert restored_lat == pytest.approx(wgs_lat, abs=1e-6)
    assert restored_lng == pytest.approx(wgs_lng, abs=1e-6)


def test_coordinates_outside_china_are_unchanged():
    assert wgs84_to_gcj02(48.8566, 2.3522) == (48.8566, 2.3522)
    assert gcj02_to_wgs84(48.8566, 2.3522) == (48.8566, 2.3522)
