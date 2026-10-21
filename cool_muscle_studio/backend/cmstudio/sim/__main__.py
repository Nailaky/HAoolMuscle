"""Ligne de commande : python -m cmstudio.sim [--mode raw|bridge] [--port 6638] ..."""

from __future__ import annotations

import argparse
import asyncio
import logging

from .server import Simulator


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="cm1sim", description="Simulateur de moteur Cool Muscle CM1")
    ap.add_argument("--mode", choices=("raw", "bridge"), default="bridge", help="raw = port série du moteur, bridge = protocole cm1_bridge")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=6638)
    ap.add_argument("--motors", type=int, default=1, help="nombre de moteurs en daisy chain (1..15)")
    ap.add_argument("--model", default="17L30")
    ap.add_argument("--fw", default="RT3.14.06")
    ap.add_argument("--no-esp", action="store_true", help="ne pas émuler les envois de l'ESP32 (mode bridge)")
    ap.add_argument("--maint-timeout", type=float, default=60.0, help="sortie automatique de maintenance après déconnexion (s, 0 = jamais)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sim = Simulator(mode=args.mode, host=args.host, port=args.port, motors=args.motors, model=args.model, fw=args.fw,
                    emulate_esp=not args.no_esp, maint_timeout_s=args.maint_timeout, verbose=args.verbose)
    try:
        asyncio.run(sim.serve_forever())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
