import pytest

from cmstudio import protocol as P


def test_parse_bridge_lines():
    assert P.parse_bridge_line("HELLO 1 NORMAL 0\n") == P.Hello(1, "NORMAL", False)
    assert P.parse_bridge_line("RX 1234 Ux.1=8") == P.RxLine(1234, "Ux.1=8")
    assert P.parse_bridge_line("RX 12 CM1 ID1 FW:RT3.14.06 HW:E") == P.RxLine(12, "CM1 ID1 FW:RT3.14.06 HW:E")
    assert P.parse_bridge_line("TX 5 LOCAL ?96.1") == P.TxLine(5, "LOCAL", "?96.1")
    assert P.parse_bridge_line("TX 5 C2 P0.1=1000") == P.TxLine(5, "C2", "P0.1=1000")
    assert P.parse_bridge_line("EVT 9 STATE MAINT 1") == P.State(9, "MAINT", True)
    assert P.parse_bridge_line("EVT 9 MAINT REFUSED MOVING") == P.MaintRefused(9, "MOVING")
    assert P.parse_bridge_line("ERR 9 FORBIDDEN K37.1=3") == P.Error(9, "FORBIDDEN", "K37.1=3")
    assert P.parse_bridge_line("PONG") == P.Pong()
    assert isinstance(P.parse_bridge_line("BIDULE x"), P.Unknown)
    with pytest.raises(P.ProtocolError):
        P.parse_bridge_line("RX abc Ux")


def test_client_formats():
    assert P.tx("?96.1") == "TX ?96.1\n"
    assert P.maint(True) == "MAINT ON\n"
    assert P.status() == "STATUS\n"
    with pytest.raises(P.ProtocolError):
        P.tx("x" * 61)
    with pytest.raises(P.ProtocolError):
        P.tx("a\nb")


def test_parse_client_line():
    assert P.parse_client_line("TX K55.1=5\n") == P.ClientCommand("TX", "K55.1=5")
    assert P.parse_client_line("MAINT OFF") == P.ClientCommand("MAINT", "OFF")
    with pytest.raises(P.ProtocolError):
        P.parse_client_line("MAINT MAYBE")
