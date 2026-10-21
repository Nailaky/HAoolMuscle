"""Transfert d'un fichier CML ligne par ligne, contre le simulateur de pont."""

import asyncio

from cmstudio.app.transfer import analyse
from test_app import _setup, _teardown

FICHIER = "/Programme de test\nA1.1=100\nS1.1=100\nP1.1=2000\nB1.1\nA1.1\nS1.1\nP1.1\nEND.1\n$.1\n"


def run(coro):
    return asyncio.run(coro)


def test_analyse(reference):
    an = analyse("test.cml", FICHIER, reference)
    assert [t for _, t in an.lignes] == ["A1.1=100", "S1.1=100", "P1.1=2000", "B1.1", "A1.1", "S1.1", "P1.1", "END.1", "$.1"]
    assert an.lignes[0][0] == 2  # numéro de ligne d'origine
    assert an.banques == ["B1"] and an.sauvegarde and not an.k37 and an.ecritures_k == []
    assert [d for d in an.diagnostics if d.severity == "erreur"] == []
    bad = analyse("bad.cml", "B1\nA1=100\nEND\nZZZ\n", reference)
    assert bad.to_dict()["erreurs"] == 1  # la constante A1=100 est hissée dans un registre N (comme Control Room)
    assert [t for _, t in bad.lignes][:3] == ["N1=100", "B1", "A1=N1"]


async def _wait_done(client, timeout=10.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        r = await client.get("/api/ponts/banc/transfert")
        st = await r.json()
        if st and st["etat"] not in ("en_attente", "en_cours"):
            return st
        await asyncio.sleep(0.05)
    raise TimeoutError("transfert non terminé")


def test_transfer_requires_maintenance_and_runs(tmp_path):
    async def go():
        sim, studio, client = await _setup(tmp_path)
        try:
            r = await client.post("/api/fichier/analyser", json={"nom": "t.cml", "contenu": FICHIER})
            assert (await r.json())["nb_lignes"] == 9
            r = await client.post("/api/ponts/banc/transfert", json={"nom": "t.cml", "contenu": FICHIER})
            assert r.status == 409
            await client.post("/api/ponts/banc/maintenance", json={"actif": True})
            r = await client.post("/api/ponts/banc/transfert", json={"nom": "bad.cml", "contenu": "B1\nZZZ\nEND\n"})
            assert r.status == 400 and (await r.json())["analyse"]["erreurs"] == 1
            r = await client.post("/api/ponts/banc/transfert", json={"nom": "t.cml", "contenu": FICHIER})
            assert r.status == 200
            st = await _wait_done(client)
            assert st["etat"] == "termine" and st["index"] == 9 and st["erreur"] is None, st
            motor = sim.chain.motors[1]
            assert motor.banks["B1"] == ["A1.1", "S1.1", "P1.1"] and motor.saved
            assert motor.regs["P"][1] == 2000
            j = (await (await client.get("/api/journal?limit=50")).json())
            assert sum(1 for e in j if e["origine"] == "fichier:t.cml") == 9
            assert any(e["ligne"].startswith("TRANSFERT t.cml") for e in j)
            hist = await (await client.get("/api/ponts/banc/historique")).json()
            assert any(e["type"] == "transfert" and e["etat"] == "termine" and e["total"] == 9 for e in hist)
        finally:
            await _teardown(sim, client)

    run(go())


def test_transfer_cancel(tmp_path):
    async def go():
        sim, studio, client = await _setup(tmp_path)
        try:
            await client.post("/api/ponts/banc/maintenance", json={"actif": True})
            contenu = "\n".join(f"T{i % 8 + 1}.1={i % 100}" for i in range(400)) + "\n"
            r = await client.post("/api/ponts/banc/transfert", json={"nom": "long.cml", "contenu": contenu})
            assert r.status == 200
            await asyncio.sleep(0.05)
            r = await client.post("/api/ponts/banc/transfert/annuler")
            assert r.status == 200
            st = await _wait_done(client)
            assert st["etat"] == "annule" and 0 < st["index"] < 400
        finally:
            await _teardown(sim, client)

    run(go())


def test_transfer_stops_without_echo(tmp_path):
    async def go():
        sim, studio, client = await _setup(tmp_path)
        try:
            await client.post("/api/ponts/banc/maintenance", json={"actif": True})
            sim.chain.master.k[23] = 1 | 8  # écho désactivé sur le moteur simulé
            r = await client.post("/api/ponts/banc/transfert", json={"nom": "t.cml", "contenu": "A1.1=5\nA2.1=6\n"})
            assert r.status == 200
            st = await _wait_done(client)
            assert st["etat"] == "erreur" and "écho" in st["erreur"] and st["index"] == 0
            r = await client.post("/api/ponts/banc/transfert", json={"nom": "t.cml", "contenu": "A1.1=5\nA2.1=6\n", "attendre_echo": False})
            st = await _wait_done(client)
            assert st["etat"] == "termine" and st["index"] == 2
        finally:
            await _teardown(sim, client)

    run(go())
