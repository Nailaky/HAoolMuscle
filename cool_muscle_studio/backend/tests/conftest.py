from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cmstudio.reference import load_reference

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def reference():
    return load_reference()


@pytest.fixture
def fixture_text():
    def _read(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return _read


async def read_until(reader: asyncio.StreamReader, predicate, timeout: float = 3.0) -> list[str]:
    """Lit des lignes jusqu'à ce que ``predicate(line)`` soit vrai ; retourne toutes les lignes lues."""
    lines: list[str] = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError(f"délai dépassé, lignes reçues : {lines}")
        raw = await asyncio.wait_for(reader.readline(), timeout=remaining)
        if not raw:
            raise ConnectionError(f"connexion fermée, lignes reçues : {lines}")
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        lines.append(line)
        if predicate(line):
            return lines
