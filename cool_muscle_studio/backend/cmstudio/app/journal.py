"""Journal des écritures envoyées au moteur (JSONL mensuel)."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Journal:
    def __init__(self, dossier: Path) -> None:
        self.dir = Path(dossier) / "journal"

    def _file(self, t: float) -> Path:
        d = datetime.fromtimestamp(t, tz=timezone.utc).astimezone()
        return self.dir / f"{d:%Y-%m}.jsonl"

    def write(self, pont: str, line: str, utilisateur: str | None, origine: str = "terminal", **extra: Any) -> dict[str, Any]:
        t = time.time()
        entry = {
            "t": datetime.fromtimestamp(t, tz=timezone.utc).astimezone().isoformat(timespec="milliseconds"),
            "pont": pont,
            "utilisateur": utilisateur or "inconnu",
            "origine": origine,
            "ligne": line,
            **extra,
        }
        self.dir.mkdir(parents=True, exist_ok=True)
        with self._file(t).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def read(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self.dir.is_dir():
            return []
        entries: list[dict[str, Any]] = []
        for f in sorted(self.dir.glob("*.jsonl"), reverse=True):
            with f.open(encoding="utf-8") as fh:
                lines = fh.readlines()
            for raw in reversed(lines):
                raw = raw.strip()
                if raw:
                    try:
                        entries.append(json.loads(raw))
                    except json.JSONDecodeError:
                        continue
                if len(entries) >= limit:
                    return entries
        return entries
