"""La copie embarquée dans le paquet (pour l'image Docker) doit être identique à la référence canonique."""

from pathlib import Path

from cmstudio.reference import find_reference_path


def test_embedded_copy_is_identical():
    canonical = find_reference_path()
    embedded = Path(__file__).resolve().parents[1] / "cmstudio" / "data" / "cml_reference.yaml"
    assert embedded.is_file(), "copie manquante : cp reference/cml_reference.yaml cool_muscle_studio/backend/cmstudio/data/"
    assert embedded.read_bytes() == canonical.read_bytes(), "copie obsolète : relancer cp reference/cml_reference.yaml cool_muscle_studio/backend/cmstudio/data/"
