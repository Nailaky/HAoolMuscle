"""Tests du backend de l'app (API, WebSocket, journal) contre le simulateur de pont."""

import asyncio
import json
from pathlib import Path

from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from cmstudio.app.config import AppConfig, BridgeConfig
from cmstudio.app.server import Studio, create_app
from cmstudio.sim import Simulator


def run(coro):
    return asyncio.run(coro)


async def _setup(tmp_path: Path, emulate_esp: bool = False):
    sim = Simulator(mode="bridge", port=0, emulate_esp=emulate_esp)
    port = await sim.start()
    config = AppConfig(ponts=[BridgeConfig("Banc", "127.0.0.1", port)], dossier=tmp_path, ingress_only=False)
    studio = Studio(config)
    app = create_app(config, studio)
    client = TestClient(TestServer(app))
    await client.start_server()
    # attendre la connexion du client de pont
    for _ in range(50):
        if studio.bridges["banc"].state.connected:
            break
        await asyncio.sleep(0.05)
    assert studio.bridges["banc"].state.connected
    return sim, studio, client


async def _teardown(sim, client):
    await client.close()
    await sim.stop()


def test_info_reference_and_state(tmp_path):
    async def go():
        sim, studio, client = await _setup(tmp_path)
        try:
            r = await client.get("/api/info")
            info = await r.json()
            assert info["ponts"][0]["nom"] == "Banc" and info["ponts"][0]["connected"]
            r = await client.get("/api/reference")
            ref = await r.json()
            assert any(p["k"] == 37 for p in ref["parametres_k"]) and ref["commandes"]
            r = await client.get("/api/ponts")
            assert (await r.json())[0]["slug"] == "banc"
            r = await client.get("/api/ponts/inconnu")
            assert r.status == 404
            r = await client.get("/")
            assert r.status == 200 and "Cool Muscle Studio" in await r.text()
            r = await client.get("/static/app.js")
            assert r.status == 200
        finally:
            await _teardown(sim, client)

    run(go())


def test_tx_rules_and_journal(tmp_path):
    async def go():
        sim, studio, client = await _setup(tmp_path)
        try:
            r = await client.post("/api/ponts/banc/tx", json={"ligne": "?99.1"})
            assert r.status == 200 and (await r.json())["lecture"] is True
            r = await client.post("/api/ponts/banc/tx", json={"ligne": "K55.1=5"})
            assert r.status == 409  # pas en maintenance
            r = await client.post("/api/ponts/banc/tx", json={"ligne": ""})
            assert r.status == 400
            r = await client.post("/api/ponts/banc/tx", json={"ligne": "*"}, headers={"X-Remote-User-Name": "cedric", "X-Remote-User-Id": "u1"})
            assert r.status == 200
            await asyncio.sleep(0.2)
            r = await client.post("/api/ponts/banc/maintenance", json={"actif": True})
            assert (await r.json())["info"] == "ALARM"  # l'arrêt d'urgence est une alarme
            r = await client.post("/api/ponts/banc/tx", json={"ligne": "*1"})
            assert r.status == 200
            await asyncio.sleep(0.2)
            r = await client.post("/api/ponts/banc/maintenance", json={"actif": True})
            body = await r.json()
            assert body["ok"] and body["mode"] == "MAINT"
            r = await client.post("/api/ponts/banc/tx", json={"ligne": "K55.1=5"})
            assert r.status == 200 and (await r.json())["journal"]["utilisateur"] == "inconnu"
            await asyncio.sleep(0.2)
            r = await client.get("/api/journal")
            j = await r.json()
            assert [e["ligne"] for e in j][:5] == ["K55.1=5", "MAINT ON", "*1", "MAINT ON", "*"]
            assert j[4]["utilisateur"] == "cedric (u1)" and j[3]["resultat"] == "ALARM"
            files = list((tmp_path / "journal").glob("*.jsonl"))
            assert len(files) == 1 and len(files[0].read_text(encoding="utf-8").splitlines()) == 5
            r = await client.get("/api/ponts/banc/historique")
            hist = await r.json()
            assert any(e["type"] == "rx" and e["line"] == "K55.1=5" and e.get("echo") for e in hist)
            assert any(e["type"] == "tx" and e["line"] == "K55.1=5" for e in hist)
            r = await client.post("/api/ponts/banc/maintenance", json={"actif": False})
            assert (await r.json())["mode"] == "NORMAL"
        finally:
            await _teardown(sim, client)

    run(go())


def test_maintenance_refused_while_moving(tmp_path):
    async def go():
        sim, studio, client = await _setup(tmp_path)
        try:
            r = await client.post("/api/ponts/banc/maintenance", json={"actif": True})
            assert (await r.json())["ok"]
            for line in ("P0.1=1000", "S0.1=10", "A0.1=10", "^.1"):
                r = await client.post("/api/ponts/banc/tx", json={"ligne": line})
                assert r.status == 200
            await asyncio.sleep(0.3)
            r = await client.post("/api/ponts/banc/maintenance", json={"actif": False})
            assert (await r.json())["mode"] == "NORMAL"
            r = await client.post("/api/ponts/banc/maintenance", json={"actif": True})
            body = await r.json()
            assert body["ok"] is False and body["info"] == "MOVING"
        finally:
            await _teardown(sim, client)

    run(go())


def test_websocket_stream_and_detect(tmp_path):
    async def go():
        sim, studio, client = await _setup(tmp_path)
        try:
            ws = await client.ws_connect("/api/ponts/banc/ws")
            msg = await ws.receive_json(timeout=3)
            assert msg["type"] == "snapshot" and msg["pont"]["connected"]
            r = await client.post("/api/ponts/banc/tx", json={"ligne": "?85.1"})
            assert r.status == 200
            seen = []
            while True:
                m = await ws.receive(timeout=3)
                assert m.type == WSMsgType.TEXT
                ev = json.loads(m.data)
                seen.append(ev)
                if ev["type"] == "rx" and ev["line"].startswith("CM1 ID1"):
                    break
            assert any(e["type"] == "tx" and e["line"] == "?85.1" for e in seen)
            assert any(e["type"] == "rx" and e["line"] == "?85.1" and e["echo"] for e in seen)
            await ws.send_json({"type": "ping"})
            assert (await ws.receive_json(timeout=3))["type"] == "pong"
            await ws.close()
            r = await client.post("/api/ponts/banc/detecter?max=3&timeout=0.3")
            body = await r.json()
            assert [m["id"] for m in body["moteurs"]] == [1]
            assert body["moteurs"][0]["info"].startswith("FW:")
            assert studio.bridges["banc"].state.my_client == "C1"
        finally:
            await _teardown(sim, client)

    run(go())


def test_ingress_guard(tmp_path):
    async def go():
        sim = Simulator(mode="bridge", port=0, emulate_esp=False)
        port = await sim.start()
        config = AppConfig(ponts=[BridgeConfig("Banc", "127.0.0.1", port)], dossier=tmp_path, ingress_only=True)
        app = create_app(config)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            r = await client.get("/api/info")  # 127.0.0.1 est toléré (tests locaux)
            assert r.status == 200
        finally:
            await client.close()
            await sim.stop()

    run(go())


def test_config_from_options():
    cfg = AppConfig.from_options({"ponts": [{"nom": "Atelier A", "hote": "cool-muscle.local", "port": 6638}], "dossier": "/share/cm", "mode_expert": True})
    assert cfg.ponts[0].slug == "atelier-a" and cfg.mode_expert and str(cfg.dossier).replace("\\", "/") == "/share/cm"
