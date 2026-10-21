"""Unités du CM1 : table K37, conversions impulsions/degrés et S/tr/min.

Source : page K Parameters (K37) et page Speed de la documentation Myostat.
"""

from __future__ import annotations

RESOLUTION_MAX = 50_000  # impulsions par tour en interne, quel que soit K37

# K37 -> (résolution en impulsions/tour, unité de vitesse en impulsions/s)
K37_TABLE: dict[int, tuple[int, int]] = {
    0: (200, 100), 1: (400, 100), 2: (500, 100), 3: (1000, 100), 4: (2000, 100),
    5: (2500, 100), 6: (5000, 100), 7: (10000, 100), 8: (25000, 100), 10: (50000, 100),
    20: (200, 10), 21: (400, 10), 22: (500, 10), 23: (1000, 10), 24: (2000, 10),
    25: (2500, 10), 26: (5000, 10), 27: (10000, 10), 28: (25000, 10), 30: (50000, 10),
    40: (300, 100), 42: (600, 100), 43: (800, 100), 44: (1200, 100), 45: (1500, 100),
    46: (3000, 100), 47: (4000, 100), 48: (6000, 100), 49: (8000, 100), 50: (12000, 100),
    60: (300, 10), 62: (600, 10), 63: (800, 10), 64: (1200, 10), 65: (1500, 10),
    66: (3000, 10), 67: (4000, 10), 68: (6000, 10), 69: (8000, 10), 70: (12000, 10),
    100: (50000, 1),
}


def resolution(k37: int) -> int:
    """Impulsions par tour pour une valeur de K37 (erreur si inconnue)."""
    return K37_TABLE[k37][0]


def speed_unit(k37: int) -> int:
    """Unité de vitesse (impulsions/s) pour une valeur de K37."""
    return K37_TABLE[k37][1]


def pulses_to_degrees(pulses: float, k37: int) -> float:
    return pulses * 360.0 / resolution(k37)


def degrees_to_pulses(degrees: float, k37: int) -> int:
    return round(degrees * resolution(k37) / 360.0)


def s_to_rpm(s: int, k37: int) -> float:
    """Vitesse en tr/min d'une valeur de registre S."""
    return s * speed_unit(k37) * 60.0 / resolution(k37)


def rpm_to_s(rpm: float, k37: int) -> int:
    return round(rpm * resolution(k37) / 60.0 / speed_unit(k37))


def convert_position(value: int, k37_from: int, k37_to: int) -> int:
    """Recalcule une position (P, R, N…) quand K37 change."""
    return round(value * resolution(k37_to) / resolution(k37_from))


def convert_speed(value: int, k37_from: int, k37_to: int) -> int:
    """Recalcule une vitesse (S) quand K37 change : même vitesse physique."""
    pps = value * speed_unit(k37_from) / resolution(k37_from)  # tours/s
    return round(pps * resolution(k37_to) / speed_unit(k37_to))


def convert_acceleration(value: int, k37_from: int, k37_to: int) -> int:
    """Recalcule une accélération (A, en 1000 imp/s²) quand K37 change."""
    return round(value * resolution(k37_to) / resolution(k37_from))
