"""Tests du simulateur en face « pont » (protocole cm1_bridge)."""

import asyncio

from cmstudio import protocol as P
from cmstudio.sim import Simulator
from cmstudio.sim.server import is_read_only
from conftest import read_until


def run(coro):
    return asyncio.run(coro)


def test_read_only_whitelist():
    assert is_read_only("?96.1") and is_read_only("?") and is_read_only("P15.1") and is_read_only("K37")
    assert is_read_only("_SKH") and is_read_only("*") and is_read_only("*1")
    assert is_read_only("?96.1,?99.1")
    assert not is_read_only("K37.1=3") and not is_read_only("^.1") and not is_read_only("(.1")
    assert not is_read_only("?96.1,^.1") and not is_read_only("")


async def _session(**kw):
    sim = Simulator(mode="bridge", emulate_esp=False, **kw)
    port = await sim.start()
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    return sim, port, reader, writer


async def send(writer, text):
    writer.write(text.encode())
    await writer.drain()


def test_hello_query_and_forbidden():
    async def go():
        sim, port, reader, writer = await _session()
        try:
            hello = (await read_until(reader, lambda l: l.startswith("HELLO")))[-1]
            assert P.parse_bridge_line(hello) == P.Hello(1, "NORMAL", False)
            await send(writer, P.tx("?99.1"))
            lines = await read_until(reader, lambda l: "Ux.1=8" in l)
            msgs = [P.parse_bridge_line(l) for l in lines]
            assert isinstance(msgs[0], P.TxLine) and msgs[0].origin == "C1" and msgs[0].line == "?99.1"
            assert isinstance(msgs[1], P.RxLine) and msgs[1].line == "?99.1"  # écho du moteur
            assert isinstance(msgs[2], P.RxLine) and msgs[2].line == "Ux.1=8"
            await send(writer, P.tx("K55.1=5"))
            err = P.parse_bridge_line((await read_until(reader, lambda l: l.startswith("ERR")))[-1])
            assert err.code == "FORBIDDEN"
            await send(writer, "TX " + "x" * 70 + "\n")
            err = P.parse_bridge_line((await read_until(reader, lambda l: l.startswith("ERR")))[-1])
            assert err.code == "TOOLONG"
            await send(writer, "BIDULE\n")
            assert P.parse_bridge_line((await read_until(reader, lambda l: l.startswith("ERR")))[-1]).code == "BADCMD"
            await send(writer, P.ping())
            assert (await read_until(reader, lambda l: l == "PONG"))[-1] == "PONG"
            await send(writer, P.status())
            st = P.parse_bridge_line((await read_until(reader, lambda l: l.startswith("EVT")))[-1])
            assert st == P.State(st.ms, "NORMAL", False)
        finally:
            writer.close()
            await sim.stop()

    run(go())


def test_estop_allowed_in_normal_mode():
    async def go():
        sim, port, reader, writer = await _session()
        try:
            await read_until(reader, lambda l: l.startswith("HELLO"))
            await send(writer, P.tx("*"))
            lines = await read_until(reader, lambda l: l.endswith("Ux.1=512"))
            assert not any(l.startswith("ERR") for l in lines)
            await send(writer, P.tx("*1"))
            await read_until(reader, lambda l: l.endswith("Ux.1=8"))
        finally:
            writer.close()
            await sim.stop()

    run(go())


def test_maintenance_cycle():
    async def go():
        sim, port, reader, writer = await _session()
        try:
            await read_until(reader, lambda l: l.startswith("HELLO"))
            await send(writer, P.maint(True))
            st = P.parse_bridge_line((await read_until(reader, lambda l: "STATE" in l))[-1])
            assert st.mode == "MAINT"
            await send(writer, P.tx("K55.1=5"))
            lines = await read_until(reader, lambda l: l.startswith("RX") and l.endswith("K55.1=5"))
            assert not any(l.startswith("ERR") for l in lines)
            # mouvement lent : S=10 -> 1000 pps à 1000 ppr, 1 tour = 1 s
            for cmd in ("P0.1=1000", "S0.1=10", "A0.1=10", "^.1"):
                await send(writer, P.tx(cmd))
            st = P.parse_bridge_line((await read_until(reader, lambda l: "STATE MAINT 1" in l))[-1])
            assert st.busy
            await send(writer, P.maint(False))
            st = P.parse_bridge_line((await read_until(reader, lambda l: "STATE NORMAL" in l))[-1])
            assert st.mode == "NORMAL" and st.busy
            await send(writer, P.maint(True))
            ref = P.parse_bridge_line((await read_until(reader, lambda l: "MAINT REFUSED" in l))[-1])
            assert ref.reason == "MOVING"
            await read_until(reader, lambda l: "STATE NORMAL 0" in l, timeout=5)
            await send(writer, P.maint(True))
            st = P.parse_bridge_line((await read_until(reader, lambda l: "STATE MAINT 0" in l))[-1])
            assert st.mode == "MAINT"
            sim.chain.motors[1].inject_alarm(4)
            await send(writer, P.maint(False))
            await read_until(reader, lambda l: "STATE NORMAL" in l)
            await send(writer, P.maint(True))
            ref = P.parse_bridge_line((await read_until(reader, lambda l: "MAINT REFUSED" in l))[-1])
            assert ref.reason == "ALARM"
        finally:
            writer.close()
            await sim.stop()

    run(go())


def test_auto_exit_maintenance_on_disconnect():
    async def go():
        sim, port, reader, writer = await _session(maint_timeout_s=0.3)
        try:
            await read_until(reader, lambda l: l.startswith("HELLO"))
            await send(writer, P.maint(True))
            await read_until(reader, lambda l: "STATE MAINT" in l)
            writer.close()
            await asyncio.sleep(0.1)
            r2, w2 = await asyncio.open_connection("127.0.0.1", port)
            hello = P.parse_bridge_line((await read_until(r2, lambda l: l.startswith("HELLO")))[-1])
            assert hello.mode == "MAINT"  # reconnexion rapide : le délai est annulé
            w2.close()
            await asyncio.sleep(0.6)
            r3, w3 = await asyncio.open_connection("127.0.0.1", port)
            hello = P.parse_bridge_line((await read_until(r3, lambda l: l.startswith("HELLO")))[-1])
            assert hello.mode == "NORMAL"
            w3.close()
        finally:
            await sim.stop()

    run(go())


def test_esp_emulation_sends_local_lines():
    async def go():
        sim = Simulator(mode="bridge", emulate_esp=True)
        port = await sim.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            lines = await read_until(reader, lambda l: l.startswith("TX") and l.endswith("LOCAL ?90.1"), timeout=5)
            assert any(l.endswith("LOCAL ?85.1") for l in lines)
            assert any(l.startswith("RX") and "CM1 ID1" in l for l in lines)
            await send(writer, P.maint(True))
            await read_until(reader, lambda l: "STATE MAINT" in l)
            before = len(sim.local_sent)
            await asyncio.sleep(0.3)
            assert len(sim.local_sent) == before  # aucun envoi local en maintenance
            await send(writer, P.maint(False))
            await read_until(reader, lambda l: l.startswith("TX") and l.endswith("LOCAL ?96.1"))
        finally:
            writer.close()
            await sim.stop()

    run(go())
