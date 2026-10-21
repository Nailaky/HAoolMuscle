"""Commandes rapides (séquences) et export de configuration contre le simulateur."""

import asyncio

from cmstudio.app.motor_ops import RE_K, RE_REG, parse_banks, statements
from test_app import _setup, _teardown


def run(coro):
    return asyncio.run(coro)


def test_grouped_k_lines_from_real_motor():
    # capture réelle du 2026-10-21 : quatre K par ligne, chiffres conservés
    lines = ["K20.1=0,K21.1=0,K22.1=200,K23.1=1", "K28.1=0800,K29.1=0900,K30.1=0000,K31.1=0000", "K88.1=400,K89.1=640,K90.1=2048"]
    parsed = {int(m.group(1)): int(m.group(3)) for st in statements(lines) if (m := RE_K.match(st))}
    assert parsed[22] == 200 and parsed[28] == 800 and parsed[90] == 2048 and len(parsed) == 11
    regs = [RE_REG.match(st).groups() for st in statements(['P0.1=250,P1.1=2000', 'V2.1="Px"'])]
    assert regs == [("P", "0", "1", "250"), ("P", "1", "1", "2000"), ("V", "2", "1", '"Px"')]


def test_parse_banks_real_format():
    # réponse réelle à ?1000 (export du 2026-10-21) : en-têtes sans END, totaux par groupe
    lines = ["B1.1", "A2.1, S2.1, P3.1+", "B2.1", "A1.1, S1.1, P2.1", "B3.1", "A1.1, S1.1, P1.1", "- Total 12 steps -",
             "L1.1", "I4.1, [2.1, [3.1", "- Total 4 steps -"]
    banks, totals = parse_banks(lines)
    assert [b["nom"] for b in banks] == ["B1", "B2", "B3", "L1"]
    assert banks[0]["lignes"] == ["A2.1,S2.1,P3.1+"] and banks[3]["lignes"] == ["I4.1,[2.1,[3.1"]
    assert totals == {"B": 12, "L": 4}
    # l'ancien format avec END reste accepté
    banks, _ = parse_banks(["B1.1", "A1.1", "END.1", "L2.1", "I1,CL3,T0", "END.1"])
    assert [b["nom"] for b in banks] == ["B1", "L2"] and banks[1]["lignes"] == ["I1,CL3,T0"]


def test_k37_position_sequence(tmp_path):
    async def go():
        sim, studio, client = await _setup(tmp_path)
        try:
            r = await client.get("/api/ponts/banc/moteurs/1/k37")
            assert await r.json() == {"k37": 3, "resolution": 1000, "unite_vitesse": 100, "moteur": 1}
            r = await client.get("/api/ponts/banc/moteurs/1/position")
            assert (await r.json())["pulses"] == 0
            r = await client.get("/api/ponts/banc/moteurs/7/k37")
            assert r.status == 504  # moteur absent
            # écriture refusée hors maintenance
            r = await client.post("/api/ponts/banc/sequence", json={"lignes": ["S0.1=100", "A0.1=100", "P0.1=1000", "^.1"]})
            assert r.status == 409
            await client.post("/api/ponts/banc/maintenance", json={"actif": True})
            r = await client.post("/api/ponts/banc/sequence", json={"nom": "aller à 1000", "lignes": ["S0.1=100", "A0.1=100", "P0.1=1000", "^.1"]})
            assert r.status == 200 and (await r.json())["transfert"]["index"] == 4
            await asyncio.sleep(1.0)
            r = await client.get("/api/ponts/banc/moteurs/1/position")
            assert (await r.json())["pulses"] == 1000
            j = await (await client.get("/api/journal?limit=10")).json()
            assert j[0]["origine"] == "commande-rapide" and j[0]["ligne"] == "^.1"
        finally:
            await _teardown(sim, client)

    run(go())


def test_export_configuration(tmp_path):
    async def go():
        sim, studio, client = await _setup(tmp_path)
        try:
            motor = sim.chain.motors[1]
            motor.regs["P"][1] = 2000
            motor.regs["V"][2] = "Px"
            motor.banks["B1"] = ["A1.1", "S1.1", "P1.1"]
            motor.banks["L1"] = ["I1,[1,T0"]
            r = await client.post("/api/ponts/banc/moteurs/1/export")
            assert r.status == 200, await r.text()
            body = await r.json()
            assert body["nb_k"] >= 67 and body["banques"] == ["B1", "L1"] and body["banniere"].startswith("CM1 ID1")
            cml = body["contenu"]
            assert "K37.1=3" in cml and "/K20.1=0" in cml and "P1.1=2000" in cml and 'V2.1="Px"' in cml
            assert "B100.1\nL100.1\nB1.1\nA1.1\nS1.1\nP1.1\nEND.1\nL1.1\nI1,[1,T0\nEND.1" in cml
            assert cml.rstrip().endswith("$.1")
            files = sorted(p.name for p in (tmp_path / "sauvegardes").iterdir())
            assert len(files) == 2 and files[0].endswith(".cml") and files[1].endswith(".json")
            r = await client.get("/api/sauvegardes")
            lst = await r.json()
            assert lst[0]["nom"] == body["fichier"] and lst[0]["json"] == body["json"]
            r = await client.get(f"/api/sauvegardes/{body['fichier']}")
            assert r.status == 200 and (await r.text()) == cml
            r = await client.get("/api/sauvegardes/../x.cml")
            assert r.status in (400, 404)
            # le fichier exporté se réanalyse sans erreur et se renverrait tel quel
            r = await client.post("/api/fichier/analyser", json={"nom": body["fichier"], "contenu": cml})
            an = await r.json()
            assert an["erreurs"] == 0 and an["banques"] == ["B1", "L1"]
        finally:
            await _teardown(sim, client)

    run(go())
