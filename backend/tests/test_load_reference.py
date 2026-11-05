from scripts.load_reference import parse_icd_line


def test_parse_icd_line():
    line = (
        "06078 F50021  1 Anorexia nervosa, binge eating/purging type, moderate".ljust(77)
        + "Long text"
    )
    assert parse_icd_line(line) == (
        "F50021",
        True,
        "Anorexia nervosa, binge eating/purging type, moderate",
        "Long text",
    )
    header = "06066 F50     0 Eating disorders".ljust(77) + "Eating disorders"
    assert parse_icd_line(header)[:2] == ("F50", False)
