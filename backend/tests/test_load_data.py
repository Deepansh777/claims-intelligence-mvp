from pathlib import Path

from scripts.load_data import TYPES, column_cast, table_name


def matches(*types: str) -> list[bool]:
    return [t in types for t, _, _, _ in TYPES]


def test_table_name():
    assert table_name(Path("output2b_admission_summary_L1.csv")) == "admission_summary_l1"
    assert table_name(Path("claims_2026-08.csv")) == "claims"
    assert table_name(Path("nexus_pcp_roster.csv")) == "nexus_pcp_roster"


def test_column_cast():
    assert column_cast("member_months", matches("bigint", "numeric"))[0] == "bigint"
    assert column_cast("member_sk", matches("bigint", "numeric")) is None
    assert column_cast("diagnosis_code_count", matches("bigint", "numeric"))[0] == "bigint"
    assert column_cast("dq_drg_unmatched", matches("boolean"))[0] == "boolean"
    assert column_cast("member_startdate", matches("date", "bigint", "numeric"))[0] == "date"
    assert column_cast("allowed_units", matches("numeric")) == (
        "numeric",
        "NULLIF(btrim(\"allowed_units\"), '')::numeric",
    )
