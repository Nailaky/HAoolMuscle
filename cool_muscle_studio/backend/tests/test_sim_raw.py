"""Tests du simulateur en face « moteur nu » (CR en entrée, CR LF en sortie)."""

import asyncio

from cmstudio.sim import Simulator
from conftest import read_until


def run(coro):
    return asyncio.run(coro)


async def _session():
    sim = Simulator(mode="raw", emulate_esp=False)
    port = await sim.start()
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    return sim, reader, writer


async def send(writer, text):
    writer.write((text + "\r").encode())
    await writer.drain()


def test_banner_echo_and_k_read():
    async def go():
        sim, reader, writer = await _session()
        try:
            await send(writer, "?85.1")
            lines = await read_until(reader, lambda l: l.startswith("CM1 "))
            assert lines == ["?85.1", "CM1 ID1 FW:RT3.14.06 HW:E"]
            await send(writer, "K55.1")
            assert (await read_until(reader, lambda l: l.startswith("K55.1=")))[-1] == "K55.1=5"
            await send(writer, "K55.1=0")
            assert (await read_until(reader, lambda l: l.startswith("Error")))[-1] == "Error.1"
            await send(writer, "K55.1=7")
            await send(writer, "K55.1")
            assert (await read_until(reader, lambda l: l.startswith("K55.1=")))[-1] == "K55.1=7"
            await send(writer, "?99.1")
            assert (await read_until(reader, lambda l: l.startswith("Ux")))[-1] == "Ux.1=8"
            await send(writer, "?90.1")
            lines = await read_until(reader, lambda l: l.startswith("K90.1="))
            assert "K37.1=3" in lines and lines[1] == "K14.1=0"
            await send(writer, "_SKH")
            assert (await read_until(reader, lambda l: l.startswith("_SKH.1=")))[-1] == "_SKH.1=1"
        finally:
            writer.close()
            await sim.stop()

    run(go())


def test_direct_move_and_position():
    async def go():
        sim, reader, writer = await _session()
        try:
            for cmd in ("P0.1=1000", "S0.1=100", "A0.1=100", "^.1"):
                await send(writer, cmd)
            lines = await read_until(reader, lambda l: l == "Ux.1=0")
            lines = await read_until(reader, lambda l: l == "Ux.1=8", timeout=5)
            await send(writer, "?96.1")
            assert (await read_until(reader, lambda l: l.startswith("Px")))[-1] == "Px.1=1000"
            # mouvement relatif ~ en résolution 50 000 : P0=1000 impulsions 50k = 20 impulsions à 1000 ppr
            await send(writer, "~.1")
            await read_until(reader, lambda l: l == "Ux.1=8", timeout=5)
            await send(writer, "?96.1")
            assert (await read_until(reader, lambda l: l.startswith("Px")))[-1] == "Px.1=1020"
            await send(writer, "|2.1")
            await send(writer, "?96.1")
            assert (await read_until(reader, lambda l: l.startswith("Px")))[-1] == "Px.1=0"
        finally:
            writer.close()
            await sim.stop()

    run(go())


def test_overspeed_alarm_and_enable():
    async def go():
        sim, reader, writer = await _session()
        try:
            # K37=3 : S=600 -> 60 000 pps / 1000 ppr = 3600 tr/min > 3000
            for cmd in ("P0.1=1000", "S0.1=600", "A0.1=100", "^.1"):
                await send(writer, cmd)
            lines = await read_until(reader, lambda l: l.startswith("Ux"))
            assert lines[-1] == "Ux.1=2"
            await send(writer, "(.1")
            assert (await read_until(reader, lambda l: l.startswith("Ux")))[-1] == "Ux.1=8"
            await send(writer, ").1")
            assert (await read_until(reader, lambda l: l.startswith("Ux")))[-1] == "Ux.1=16"
            await send(writer, "(.1")
            await read_until(reader, lambda l: l == "Ux.1=8")
        finally:
            writer.close()
            await sim.stop()

    run(go())


def test_estop_and_alarm_injection():
    async def go():
        sim, reader, writer = await _session()
        try:
            await send(writer, "*")
            assert (await read_until(reader, lambda l: l.startswith("Ux")))[-1] == "Ux.1=512"
            await send(writer, "^.1")  # ignoré en arrêt d'urgence
            await send(writer, "?99.1")
            assert (await read_until(reader, lambda l: l.startswith("Ux")))[-1] == "Ux.1=512"
            await send(writer, "*1")
            assert (await read_until(reader, lambda l: l.startswith("Ux")))[-1] == "Ux.1=8"
            sim.chain.motors[1].inject_alarm(4)
            assert (await read_until(reader, lambda l: l.startswith("Ux")))[-1] == "Ux.1=4"
            await send(writer, "(.1")
            assert (await read_until(reader, lambda l: l.startswith("Ux")))[-1] == "Ux.1=8"
        finally:
            writer.close()
            await sim.stop()

    run(go())


def test_bank_record_dump_and_run():
    async def go():
        sim, reader, writer = await _session()
        try:
            for cmd in ("A1.1=100", "S1.1=100", "P1.1=2000", "T1.1=50", "B1.1", "A1.1", "S1.1", "P1.1", "T1", "END.1"):
                await send(writer, cmd)
            await send(writer, "?1000.1")
            lines = await read_until(reader, lambda l: l.startswith("Steps"))
            assert lines[-6:] == ["B1.1", "A1.1", "S1.1", "P1.1", "T1", "END.1", "Steps.1=4/200"][-6:]
            assert lines[-7] == "B1.1"
            await send(writer, "[1.1")
            await read_until(reader, lambda l: l == "Ux.1=0")
            await read_until(reader, lambda l: l == "Ux.1=8", timeout=5)
            await send(writer, "?96.1")
            assert (await read_until(reader, lambda l: l.startswith("Px")))[-1] == "Px.1=2000"
            await send(writer, "$.1")
            assert (await read_until(reader, lambda l: l.startswith("Saved")))[-1] == "Saved.1"
            await send(writer, "B100.1")
            await send(writer, "?1000.1")
            lines = await read_until(reader, lambda l: l.startswith("Steps"))
            assert lines[-1] == "Steps.1=0/200"
        finally:
            writer.close()
            await sim.stop()

    run(go())


def test_logic_bank_scans_and_branches():
    async def go():
        sim, reader, writer = await _session()
        try:
            for cmd in ("K87.1=10", "V1.1=0", "V2.1=5", "L1.1", "V1=V1+V2;", "V1>=V2, ?99, T0", "END.1", "[L1.1"):
                await send(writer, cmd)
            lines = await read_until(reader, lambda l: l == "Ux.1=8", timeout=3)
            await send(writer, "]L.1")
            await send(writer, "V1.1")
            got = (await read_until(reader, lambda l: l.startswith("V1.1=")))[-1]
            assert int(got.split("=")[1]) >= 5
        finally:
            writer.close()
            await sim.stop()

    run(go())


def test_two_motors_addressing():
    async def go():
        sim = Simulator(mode="raw", emulate_esp=False, motors=2)
        port = await sim.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            await send(writer, "P1.2=500")
            await send(writer, "P2=50")  # sans id : dernier moteur adressé (2)
            await send(writer, "P2.2")
            assert (await read_until(reader, lambda l: l.startswith("P2.2=")))[-1] == "P2.2=50"
            await send(writer, "P2.1")
            assert (await read_until(reader, lambda l: l.startswith("P2.1=")))[-1] == "P2.1=0"
            await send(writer, "?85.3")  # moteur absent : pas de réponse, seulement l'écho
            await send(writer, "?99.1")
            lines = await read_until(reader, lambda l: l.startswith("Ux"))
            assert "?85.3" in lines and not any(l.startswith("CM1 ID3") for l in lines)
        finally:
            writer.close()
            await sim.stop()

    run(go())
