"""Serveur web de l'app (aiohttp) : API, WebSocket du terminal, fichiers statiques.

Toutes les URL sont relatives (ingress Home Assistant) ; l'en-tête
X-Ingress-Path n'est pas nécessaire côté serveur car le frontend construit ses
URL à partir de document.baseURI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

from .. import __version__
from ..reference import load_reference
from ..sim.server import is_read_only
from .bridge_client import BridgeClient
from .config import AppConfig, BridgeConfig
from .journal import Journal

log = logging.getLogger("cmstudio.app")
STATIC_DIR = Path(__file__).resolve().parent / "static"
INGRESS_GATEWAY = "172.30.32.2"
_RE_BANNER = re.compile(r"CM1\s+ID(\d+)\s+(.*)")


class Studio:
    """État partagé de l'app : ponts, journal, référence."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.bridges: dict[str, BridgeClient] = {}
        for b in config.ponts:
            self.add_bridge(b)
        self.journal = Journal(config.dossier)
        self.reference = load_reference()

    def add_bridge(self, b: BridgeConfig) -> BridgeClient:
        client = BridgeClient(b.nom, b.hote, b.port)
        self.bridges[b.slug] = client
        return client

    async def start(self) -> None:
        for c in self.bridges.values():
            c.start()

    async def stop(self) -> None:
        for c in self.bridges.values():
            await c.stop()

    def bridge(self, slug: str) -> BridgeClient:
        try:
            return self.bridges[slug]
        except KeyError:
            raise web.HTTPNotFound(text=f"pont inconnu : {slug}") from None

    def reference_payload(self) -> dict[str, Any]:
        ref = self.reference
        return {
            "commandes": [
                {"cmd": c.get("cmd"), "nom": c.get("nom"), "syntaxe": c.get("syntaxe"), "danger": c.get("danger"), "note": c.get("note")}
                for c in ref.commands
            ],
            "requetes": [{"cmd": q.get("cmd"), "retour": q.get("retour"), "statut": q.get("statut")} for q in ref.queries],
            "parametres_k": [
                {"k": p.num, "nom": p.nom, "unite": p.unite, "min": p.min, "max": p.max, "defaut": p.defaut, "type": p.type,
                 "valeurs": p.valeurs, "avertissement": p.avertissement}
                for p in sorted(ref.k_params.values(), key=lambda p: p.num)
            ],
            "registres": [{"lettre": f.lettre, "nom": f.nom, "indices": f"{f.index_min}..{f.index_max}", "unite": f.unite} for f in ref.registers.values()],
            "etats": [{"valeur": s.valeur, "nom": s.nom, "alarme": s.alarme} for s in ref.status_codes],
        }


# ---------------------------------------------------------------------------- middlewares
@web.middleware
async def ingress_guard(request: web.Request, handler):
    studio: Studio = request.app["studio"]
    if studio.config.ingress_only:
        peer = request.remote or ""
        if peer != INGRESS_GATEWAY and not peer.startswith("127."):
            raise web.HTTPForbidden(text="accès réservé à la passerelle ingress de Home Assistant")
    return await handler(request)


def _user(request: web.Request) -> str | None:
    name = request.headers.get("X-Remote-User-Display-Name") or request.headers.get("X-Remote-User-Name")
    uid = request.headers.get("X-Remote-User-Id")
    if name and uid:
        return f"{name} ({uid})"
    return name or uid


# ---------------------------------------------------------------------------- routes
async def index(request: web.Request) -> web.Response:
    # sous ingress, l'URL doit se terminer par « / » pour que les chemins relatifs fonctionnent
    ingress_path = request.headers.get("X-Ingress-Path")
    if ingress_path and not request.path.endswith("/") and request.path == "":
        raise web.HTTPFound(ingress_path + "/")
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return web.Response(text=html, content_type="text/html", charset="utf-8")


async def api_info(request: web.Request) -> web.Response:
    studio: Studio = request.app["studio"]
    return web.json_response({
        "version": __version__,
        "mode_expert": studio.config.mode_expert,
        "dossier": str(studio.config.dossier),
        "utilisateur": _user(request),
        "ponts": [c.snapshot() for c in studio.bridges.values()],
    })


async def api_reference(request: web.Request) -> web.Response:
    studio: Studio = request.app["studio"]
    return web.json_response(studio.reference_payload())


async def api_bridges(request: web.Request) -> web.Response:
    studio: Studio = request.app["studio"]
    return web.json_response([{"slug": s, **c.snapshot()} for s, c in studio.bridges.items()])


async def api_bridge_state(request: web.Request) -> web.Response:
    studio: Studio = request.app["studio"]
    c = studio.bridge(request.match_info["slug"])
    return web.json_response({"slug": request.match_info["slug"], **c.snapshot()})


async def api_history(request: web.Request) -> web.Response:
    studio: Studio = request.app["studio"]
    c = studio.bridge(request.match_info["slug"])
    since = int(request.query.get("since", "0"))
    return web.json_response([e.to_dict() for e in c.history if e.seq > since])


async def api_tx(request: web.Request) -> web.Response:
    studio: Studio = request.app["studio"]
    c = studio.bridge(request.match_info["slug"])
    data = await request.json()
    line = str(data.get("ligne", "")).strip()
    if not line:
        raise web.HTTPBadRequest(text="ligne vide")
    if len(line) > 60:
        raise web.HTTPBadRequest(text="ligne de plus de 60 caractères")
    if not c.state.connected:
        raise web.HTTPServiceUnavailable(text="pont non connecté")
    lecture = is_read_only(line)
    if not lecture and c.state.mode != "MAINT" and not line.startswith("*"):
        raise web.HTTPConflict(text="écriture refusée : le pont n'est pas en mode maintenance")
    try:
        await c.send(line)
    except ConnectionError as exc:
        raise web.HTTPServiceUnavailable(text=str(exc)) from None
    entry = None
    if not lecture or line.startswith("*"):  # l'arrêt d'urgence est journalisé aussi
        entry = studio.journal.write(c.name, line, _user(request), origine=str(data.get("origine", "terminal")))
    return web.json_response({"ok": True, "lecture": lecture, "journal": entry})


async def api_maint(request: web.Request) -> web.Response:
    studio: Studio = request.app["studio"]
    c = studio.bridge(request.match_info["slug"])
    data = await request.json()
    on = bool(data.get("actif"))
    if not c.state.connected:
        raise web.HTTPServiceUnavailable(text="pont non connecté")
    ok, info = await c.set_maintenance(on)
    studio.journal.write(c.name, f"MAINT {'ON' if on else 'OFF'}", _user(request), origine="maintenance", resultat=info)
    return web.json_response({"ok": ok, "mode": c.state.mode, "info": info})


async def api_detect(request: web.Request) -> web.Response:
    """Détecte les moteurs présents : ?85.1 à ?85.15 (lectures, autorisées en mode normal)."""
    studio: Studio = request.app["studio"]
    c = studio.bridge(request.match_info["slug"])
    if not c.state.connected:
        raise web.HTTPServiceUnavailable(text="pont non connecté")
    maxid = min(15, max(1, int(request.query.get("max", "15"))))
    timeout = float(request.query.get("timeout", "0.4"))
    found: list[dict[str, Any]] = []
    for mid in range(1, maxid + 1):
        await c.send(f"?85.{mid}")
        seen = await c.wait_for_rx(lambda l, m=mid: bool(_RE_BANNER.match(l)) and _RE_BANNER.match(l).group(1) == str(m), timeout)
        for ev in seen:
            m = _RE_BANNER.match(ev.line)
            if m and int(m.group(1)) == mid:
                found.append({"id": mid, "banniere": ev.line, "info": m.group(2)})
                break
    return web.json_response({"moteurs": found})


async def api_journal(request: web.Request) -> web.Response:
    studio: Studio = request.app["studio"]
    return web.json_response(studio.journal.read(int(request.query.get("limit", "200"))))


async def ws_terminal(request: web.Request) -> web.WebSocketResponse:
    studio: Studio = request.app["studio"]
    c = studio.bridge(request.match_info["slug"])
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    q = c.subscribe()
    await ws.send_json({"type": "snapshot", "pont": c.snapshot(), "historique": [e.to_dict() for e in list(c.history)[-300:]]})

    async def pump() -> None:
        while True:
            ev = await q.get()
            await ws.send_json(ev.to_dict())

    task = asyncio.create_task(pump())
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        task.cancel()
        c.unsubscribe(q)
    return ws


def create_app(config: AppConfig, studio: Studio | None = None) -> web.Application:
    app = web.Application(middlewares=[ingress_guard])
    app["studio"] = studio or Studio(config)
    app.router.add_get("/", index)
    app.router.add_get("/api/info", api_info)
    app.router.add_get("/api/reference", api_reference)
    app.router.add_get("/api/ponts", api_bridges)
    app.router.add_get("/api/ponts/{slug}", api_bridge_state)
    app.router.add_get("/api/ponts/{slug}/historique", api_history)
    app.router.add_post("/api/ponts/{slug}/tx", api_tx)
    app.router.add_post("/api/ponts/{slug}/maintenance", api_maint)
    app.router.add_post("/api/ponts/{slug}/detecter", api_detect)
    app.router.add_get("/api/ponts/{slug}/ws", ws_terminal)
    app.router.add_get("/api/journal", api_journal)
    app.router.add_static("/static", STATIC_DIR, show_index=False)

    async def on_startup(app: web.Application) -> None:
        await app["studio"].start()

    async def on_cleanup(app: web.Application) -> None:
        await app["studio"].stop()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app
