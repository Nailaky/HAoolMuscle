"""Formats des réponses du moteur simulé.

Chaque entrée indique son statut :
- documente : forme donnée par la documentation Myostat ;
- observe   : forme vue en production par le YAML ESPHome existant ;
- hypothese : forme inventée pour le simulateur, À REMPLACER par la capture réelle.

Les placeholders : {id} identifiant moteur, {v} valeur, {n} numéro, {reg} lettre,
{line} ligne reçue, {fw}/{hw} versions, {q} numéro de requête, {used} pas utilisés.
"""

from __future__ import annotations

FORMATS: dict[str, str] = {
    "echo": "{line}",
    "banner": "CM1 ID{id} FW:{fw} HW:{hw}",
    "k": "K{n}.{id}={v}",
    "reg": "{reg}{n}.{id}={v}",
    "ux": "Ux.{id}={v}",
    "px": "Px.{id}={v}",
    "ex": "Ex.{id}={v}",
    "sx": "Sx.{id}={v}",
    "tx": "Tx.{id}={v}",
    "query_generic": "?{q}.{id}={v}",
    "saved": "Saved.{id}",
    "skh": "_SKH.{id}={v}",
    "error": "Error.{id}",
    "bank_header": "{name}.{id}",
    "bank_end": "END.{id}",
    "steps": "Steps.{id}={used}/200",
    "end_bank": "End!",
    "cant_back": "Can't Back!",
    "math_echo": "{reg}{n}.{id}={v}",
    "stream": "{name}.{id}={v}",
}

STATUS: dict[str, str] = {
    "echo": "hypothese (écho de la ligne telle quelle)",
    "banner": "observe (brief utilisateur)",
    "k": "observe (capture réelle 2026-10-21 : ?90 renvoie 4 K par ligne séparés par des virgules, ex. K20.1=0,K21.1=0,K22.1=200,K23.1=1)",
    "reg": "documente (UG §10.3 : P15.1=#)",
    "ux": "observe (YAML ESPHome)",
    "px": "observe (YAML ESPHome)",
    "ex": "hypothese (table Modbus : Ex)",
    "sx": "hypothese (table Modbus : Sx)",
    "tx": "hypothese (table Modbus : Tx)",
    "query_generic": "hypothese",
    "saved": "documente (UG §9.1)",
    "skh": "hypothese",
    "error": "hypothese",
    "bank_header": "hypothese",
    "bank_end": "hypothese",
    "steps": "hypothese",
    "end_bank": "documente (UG §9.1)",
    "cant_back": "documente (UG §9.1)",
    "math_echo": "hypothese (UG §10.7.2 dit seulement que le résultat est renvoyé)",
    "stream": "hypothese (K66=7 documenté comme Tx.1=xxx)",
}

# nom de ligne de streaming par valeur de K66 (hypothèses sauf 7)
STREAM_NAMES: dict[int, str] = {1: "St", 2: "Px", 3: "Sx", 4: "Ix", 5: "Px", 6: "Sx", 7: "Tx"}
