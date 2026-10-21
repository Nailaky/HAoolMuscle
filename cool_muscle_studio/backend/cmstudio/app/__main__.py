"""Lancement : python -m cmstudio.app [--dev] [--bridge nom=hote:port] [--port 8099]"""

from __future__ import annotations

import argparse
import asyncio
import logging

from aiohttp import web

from ..sim.server import Simulator
from .config import AppConfig, BridgeConfig
from .server import Studio, create_app


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="cmstudio.app", description="Serveur web Cool Muscle Studio")
    ap.add_argument("--dev", action="store_true", help="démarre un simulateur de pont en interne")
    ap.add_argument("--bridge", action="append", default=[], metavar="NOM=HOTE:PORT", help="pont à ajouter (répétable)")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--open", action="store_true", help="accepter toutes les adresses (hors ingress)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = AppConfig.load()
    for spec in args.bridge:
        nom, _, addr = spec.partition("=")
        hote, _, port = addr.partition(":")
        config.ponts.append(BridgeConfig(nom or hote, hote, int(port or 6638)))
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port
    if args.open or args.dev:
        config.ingress_only = False
    if args.dev:
        config.dev = True
        if not args.host:
            config.host = "127.0.0.1"

    asyncio.run(_serve(config))


async def _serve(config: AppConfig) -> None:
    sim: Simulator | None = None
    if config.dev:
        sim = Simulator(mode="bridge", port=0, emulate_esp=True)
        port = await sim.start()
        config.ponts.insert(0, BridgeConfig("Simulateur", "127.0.0.1", port))
        logging.getLogger("cmstudio.app").info("simulateur de pont sur 127.0.0.1:%d", port)
    studio = Studio(config)
    app = create_app(config, studio)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.host, config.port)
    await site.start()
    logging.getLogger("cmstudio.app").info("Cool Muscle Studio sur http://%s:%d/", config.host, config.port)
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await runner.cleanup()
        if sim:
            await sim.stop()


if __name__ == "__main__":
    main()
