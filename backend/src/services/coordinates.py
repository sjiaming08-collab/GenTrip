"""Coordinate conversion at external provider boundaries.

GenTrip stores and computes with WGS-84 coordinates. Amap Web Service uses
GCJ-02, so conversions must happen immediately before and after Amap calls.
"""

from __future__ import annotations

import math


_PI = math.pi
_A = 6378245.0
_EE = 0.00669342162296594323


def _outside_china(lat: float, lng: float) -> bool:
    return lng < 72.004 or lng > 137.8347 or lat < 0.8293 or lat > 55.8271


def _transform_lat(lng: float, lat: float) -> float:
    value = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat
    value += 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    value += (20.0 * math.sin(6.0 * lng * _PI) + 20.0 * math.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    value += (20.0 * math.sin(lat * _PI) + 40.0 * math.sin(lat / 3.0 * _PI)) * 2.0 / 3.0
    value += (160.0 * math.sin(lat / 12.0 * _PI) + 320.0 * math.sin(lat * _PI / 30.0)) * 2.0 / 3.0
    return value


def _transform_lng(lng: float, lat: float) -> float:
    value = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng
    value += 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    value += (20.0 * math.sin(6.0 * lng * _PI) + 20.0 * math.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    value += (20.0 * math.sin(lng * _PI) + 40.0 * math.sin(lng / 3.0 * _PI)) * 2.0 / 3.0
    value += (150.0 * math.sin(lng / 12.0 * _PI) + 300.0 * math.sin(lng / 30.0 * _PI)) * 2.0 / 3.0
    return value


def wgs84_to_gcj02(lat: float, lng: float) -> tuple[float, float]:
    """Convert a WGS-84 latitude/longitude pair to GCJ-02."""

    if _outside_china(lat, lng):
        return lat, lng
    delta_lat = _transform_lat(lng - 105.0, lat - 35.0)
    delta_lng = _transform_lng(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * _PI
    magic = math.sin(rad_lat)
    magic = 1 - _EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    delta_lat = delta_lat * 180.0 / ((_A * (1 - _EE)) / (magic * sqrt_magic) * _PI)
    delta_lng = delta_lng * 180.0 / (_A / sqrt_magic * math.cos(rad_lat) * _PI)
    return lat + delta_lat, lng + delta_lng


def gcj02_to_wgs84(lat: float, lng: float) -> tuple[float, float]:
    """Convert GCJ-02 to WGS-84 using a bounded iterative inverse."""

    if _outside_china(lat, lng):
        return lat, lng
    wgs_lat, wgs_lng = lat, lng
    for _ in range(8):
        converted_lat, converted_lng = wgs84_to_gcj02(wgs_lat, wgs_lng)
        delta_lat = converted_lat - lat
        delta_lng = converted_lng - lng
        wgs_lat -= delta_lat
        wgs_lng -= delta_lng
        if abs(delta_lat) < 1e-7 and abs(delta_lng) < 1e-7:
            break
    return wgs_lat, wgs_lng
