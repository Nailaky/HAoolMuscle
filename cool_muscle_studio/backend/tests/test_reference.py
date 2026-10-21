from cmstudio.reference import KParam


def test_reference_loads(reference):
    assert reference.k(37) is not None
    assert len(reference.k_params) >= 60
    assert reference.status(512).alarme is True
    assert reference.registers["P"].index_max == 25
    assert reference.registers["T"].index_min == 0


def test_k37_enum(reference):
    k37 = reference.k(37)
    assert k37.type == "enum"
    assert k37.check(10) == []
    assert k37.check(11) != []


def test_k_int_range(reference):
    k55 = reference.k(55)
    assert k55.check(5) == []
    assert k55.check(0)
    assert k55.check(101)


def test_k_digits(reference):
    k25 = reference.k(25)
    assert k25.nb_chiffres == 4
    assert k25.check(3333) == []
    assert k25.check(3330)  # chiffre 0 interdit (min 1)
    assert k25.check(33333)  # cinq chiffres
    k27 = reference.k(27)
    assert k27.check(34) == []  # N1=4 (CCW), N2=3 (CW)
    k30 = reference.k(30)  # "comme K27" résolu
    assert k30.valeurs_chiffre == k27.valeurs_chiffre
    k34 = reference.k(34)
    assert k34.check(21) == []
    assert k34.check(99) == []
    assert k34.check(100)


def test_k_bits(reference):
    k23 = reference.k(23)
    assert k23.check(1) == []
    assert k23.check(1 | 8 | 32) == []
    assert k23.check(64)


def test_k_defaults(reference):
    d = reference.k_defaults()
    assert d[37] == 3
    assert d[23] == 1
    assert d[70] == 1


def test_undocumented_k(reference):
    assert reference.k(51).documente is False
    assert reference.k(51).check(5) == []


def test_kparam_dataclass_direct():
    p = KParam(num=1, nom="x", type="int", min=0, max=3)
    assert p.check(4)
