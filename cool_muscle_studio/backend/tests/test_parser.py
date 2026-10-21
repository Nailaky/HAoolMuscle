from cmstudio.cml import Kind, parse_line, parse_program, parse_statement


def st(text, in_bank=False):
    return parse_statement(text, in_bank)


def test_register_writes():
    s = st("P0.1=1000")
    assert (s.kind, s.reg, s.index, s.motor, s.value.int_value) == (Kind.REG_WRITE, "P", 0, 1, 1000)
    s = st("K37.1=10")
    assert (s.kind, s.reg, s.index, s.value.int_value) == (Kind.REG_WRITE, "K", 37, 10)
    s = st('V2.1="Px"')
    assert s.value.kind == "str"
    s = st("P1.1=P2.1+V1.1")
    assert s.value.kind == "expr" and s.value.refs == ("P2", "V1")
    s = st("a1=100")
    assert (s.reg, s.index, s.value.int_value) == ("A", 1, 100)
    s = st("S.1=50")  # mode direct : lettre seule = registre 0
    assert (s.reg, s.index, s.motor) == ("S", 0, 1)
    s = st("V1=-50")
    assert s.value.int_value == -50


def test_register_read_and_queries():
    assert st("P15.1").kind is Kind.REG_READ
    s = st("?96.2")
    assert (s.kind, s.arg, s.motor) == (Kind.QUERY, "96", 2)
    assert st("?").arg == ""
    assert st("?P.1").arg == "P"
    assert st("?1000").arg == "1000"


def test_direct_commands():
    assert (st("^.1").command, st("^.1").motor) == ("^", 1)
    assert st("^5").arg == "5"
    assert st("~.1").command == "~"
    assert (st("|2.3").command, st("|2.3").arg, st("|2.3").motor) == ("|", "2", 3)
    assert st("|.1").arg is None
    assert st("|11").arg == "11"
    assert st("(.1").command == "("
    assert st(").2").command == ")"
    assert (st("O1.2").command, st("O1.2").arg) == ("O", "1")
    assert st("F2").command == "F"
    assert st("$.1").command == "$"
    assert st("[L3.1").arg == "L3"
    assert st("[1.1").arg == "1"
    assert st("].1").command == "]"
    assert st("]L.1").command == "]L"
    assert st("}.1").command == "}"
    assert st(">.1").command == ">"
    assert st("<.1").command == "<"
    assert st("*").command == "*"
    assert st("*1").command == "*1"
    assert st("B100").command == "B100"
    assert st("L100.2").command == "L100"
    s = st("_SKH=0")
    assert s.kind is Kind.COMMAND and s.command == "_SKH" and s.value.int_value == 0
    assert st("_SKH").kind is Kind.COMMAND
    assert st("_mop=2").command == "_MOP"
    s = st("D12=103490138")
    assert (s.command, s.arg, s.value.int_value) == ("D", "12", 103490138)
    assert (st("{0").command, st("{0").arg) == ("{", "0")
    assert st("FFFFFFFFF").command == "FFFFFFFFF"


def test_banks_and_steps():
    s = st("B1.1")
    assert (s.kind, s.command, s.index, s.motor) == (Kind.BANK_START, "B", 1, 1)
    assert st("l2").kind is Kind.BANK_START and st("l2").command == "L"
    assert st("END.1").kind is Kind.BANK_END
    assert st("end").kind is Kind.BANK_END
    s = st("P4.1+", in_bank=True)
    assert (s.kind, s.command, s.index, s.plus) == (Kind.STEP, "P", 4, True)
    assert st("X0", True).command == "X" and st("X0", True).index == 0
    assert st("X-", True).arg == "-"
    assert st("Y4.1", True).command == "Y"
    assert st("Q4", True).command == "Q" and st("Z4", True).command == "Z"
    assert st("C2", True).command == "C" and st("J2", True).command == "J"
    assert st("CL2", True).command == "CL" and st("JL1", True).command == "JL"
    s = st("@2.1-", True)
    assert (s.command, s.index, s.minus) == ("@", 2, True)
    assert st("W0", True).command == "W"
    assert st("T3", True).command == "T"
    assert st("I1.1", True).command == "I"
    s = st("A1,", True)
    assert s.kind is Kind.UNKNOWN or s.command == "A"


def test_merge_and_unknown():
    s = st("P1.1;", in_bank=True)
    assert s.merge and s.kind is Kind.STEP
    assert st("V1=V2+V3;", True).merge
    assert st("ZZZ.1").kind is Kind.UNKNOWN
    assert st("").kind is Kind.UNKNOWN


def test_line_branch_and_junction():
    pl = parse_line("I1.1,C2.1,W0", 1, in_bank=True)
    b = pl.statements[0]
    assert b.kind is Kind.BRANCH and b.condition == "I1.1"
    assert b.then[0].command == "C" and b.otherwise[0].command == "W"
    pl = parse_line("V1>=V2, ?99, ?96", 1)
    b = pl.statements[0]
    assert b.kind is Kind.BRANCH and b.then[0].kind is Kind.QUERY
    pl = parse_line("I1.1,?96:?97,W0", 1, True)
    j = pl.statements[0].then[0]
    assert j.kind is Kind.JUNCTION and [c.arg for c in j.children] == ["96", "97"]
    pl = parse_line("V0==N10,]:],CL3", 1, True)
    assert pl.statements[0].then[0].kind is Kind.JUNCTION
    pl = parse_line("A1,S1,P1", 1, True)
    assert [s.command for s in pl.statements] == ["A", "S", "P"]
    pl = parse_line("P1.2,P3.1", 1, True)
    assert [s.motor for s in pl.statements] == [2, 1]
    pl = parse_line('V3.1="a,b"', 1)
    assert len(pl.statements) == 1 and pl.statements[0].value.text == '"a,b"'


def test_comments_and_blank():
    assert parse_line("/commentaire", 1).is_comment
    assert parse_line("   ", 1).is_empty
    assert parse_line("//cmp", 1).is_comment


def test_program_structure(fixture_text):
    prog = parse_program(fixture_text("binary_inputs.cml"))
    assert [b.name for b in prog.banks] == ["L1", "L2", "L3", "B1", "B2", "B3"]
    assert prog.diagnostics == []
    assert prog.step_count() == 8 + 2 + 3 + 1 + 1 + 1
    assert prog.bank("l2").motor == 1
    assert prog.bank("B1").lines[0].in_bank


def test_program_unterminated_bank():
    prog = parse_program("B1\nA1,S1,P1\nB2\nEND\n")
    codes = [d.code for d in prog.diagnostics]
    assert "E002" in codes
    prog = parse_program("END\n")
    assert prog.diagnostics[0].code == "E002"
    prog = parse_program("B1\nA1,S1,P1\n")
    assert prog.diagnostics[0].code == "E002" and not prog.banks[0].closed
