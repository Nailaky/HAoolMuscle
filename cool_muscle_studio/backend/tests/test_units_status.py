import pytest

from cmstudio import status, units


def test_k37_table():
    assert units.resolution(10) == 50000
    assert units.speed_unit(10) == 100
    assert units.resolution(3) == 1000
    assert units.speed_unit(100) == 1
    with pytest.raises(KeyError):
        units.resolution(11)


def test_rpm_roundtrip_matches_esp_yaml():
    # le YAML actuel calcule S = rpm * 50000 / 60 / 100 pour K37 = 10
    assert units.rpm_to_s(120, 10) == 1000
    assert units.s_to_rpm(1000, 10) == pytest.approx(120.0)


def test_degrees():
    assert units.degrees_to_pulses(180, 10) == 25000
    assert units.pulses_to_degrees(25000, 10) == pytest.approx(180.0)
    assert units.degrees_to_pulses(1, 10) == 139


def test_conversions_on_k37_change():
    assert units.convert_position(500, 3, 10) == 25000
    assert units.convert_speed(50, 3, 10) == 2500  # 5000 pps -> 250000 pps en unités de 100
    assert units.convert_acceleration(10, 3, 10) == 500


def test_status_decode():
    assert status.decode(0).en_mouvement
    assert status.decode(8).en_position and not status.decode(8).alarme
    s = status.decode(40)
    assert [f.valeur for f in s.flags] == [8, 32]
    assert status.decode(512).arret_urgence and status.decode(512).alarme
    assert status.decode(16).desactive and not status.decode(16).alarme
    assert status.decode(4).alarme
    assert status.decode(1024).inconnus == 1024
    assert "Surcharge" in status.decode(4).texte
