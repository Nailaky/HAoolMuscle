from cmstudio.cml import parse_program
from cmstudio.cml.cmp import compile_cmp, preprocess
from cmstudio.cml.validate import validate


def codes(diags):
    return [d.code for d in diags]


def test_preprocess_comments_define_var():
    src = '#define fast 100\nvar Home P1\n// commentaire\nS1=fast /* bloc\nsur deux lignes */\nHome=5000\nV1="fast"\n'
    res = preprocess(src)
    lines = res.cml.split("\n")
    assert len(lines) == len(src.split("\n"))  # numérotation conservée
    assert lines[0] == "" and lines[1] == ""
    assert lines[3] == "S1=100"
    assert lines[5] == "P1=5000"
    assert lines[6] == 'V1="fast"'  # pas de substitution entre guillemets
    assert res.defines == {"fast": "100"} and res.variables == {"Home": "P1"}


def test_compile_allocates_constants(reference):
    src = "B1.1\nA1.1=100\nEND.1\n"
    res = compile_cmp(src)
    assert res.diagnostics == []
    assert res.cml.split("\n")[:4] == ["N1.1=100", "B1.1", "A1.1=N1.1", "END.1"]
    assert res.constants == {"N1.1": 100}
    assert res.line_map[:4] == [1, 1, 2, 3]
    prog = parse_program(res.cml)
    assert codes(validate(prog, reference)) == ["I020"]


def test_compile_modbus_example(fixture_text, reference):
    res = compile_cmp(fixture_text("modbus_program.cmp"))
    assert "old_ControlWord" not in res.cml
    prog = parse_program(res.cml)
    diags = validate(prog, reference)
    assert [d for d in diags if d.severity == "erreur"] == [], diags
    assert [b.name for b in prog.banks] == ["L1", "L2", "L3"]
    assert "W011" in codes(diags)  # K23 touche les événements/écho


def test_figure_eight_example(fixture_text, reference):
    res = compile_cmp(fixture_text("figure_eight.cmp"))
    prog = parse_program(res.cml)
    diags = validate(prog, reference)
    assert [d for d in diags if d.severity == "erreur"] == [], diags
    assert [b.name for b in prog.banks] == ["L1", "L2", "B1"]


def test_validate_k_and_registers(reference):
    prog = parse_program("K55.1=0\nK37.1=10\nK20.1=1\nK999=1\nP26.1=5\nP1=2000000000\nK51=3\n")
    c = codes(validate(prog, reference))
    assert c.count("E005") == 2  # K55 hors plage, K999 inconnu
    assert "W010" in c and "W011" in c
    assert c.count("E006") == 2  # P26 indice, P1 valeur
    assert "W013" in c


def test_validate_bank_rules(reference):
    prog = parse_program("B1\nA1.1=100\nA1,S1,P1,A2,S2,P2,A3,S3,P3,A4,S4,P4,A5,S5,P5\nP26\nI5\nX300\nEND\n$\n")
    c = codes(validate(prog, reference))
    assert "E003" in c and "E004" in c and c.count("E008") == 3
    assert "I020" not in c
    prog = parse_program("ZZZ\n")
    assert codes(validate(prog, reference)) == ["E001"]


def test_validate_step_count(reference):
    body = "\n".join("T0" for _ in range(201))
    prog = parse_program(f"B1\n{body}\nEND\n")
    assert "E007" in codes(validate(prog, reference))
