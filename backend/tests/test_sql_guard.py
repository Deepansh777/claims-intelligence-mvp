import pytest

from app.llm.schemas import QueryError
from app.services.analytics_sql import validate_sql


def test_allows_select_and_with():
    assert validate_sql("-- Raw fallback: x\nWITH a AS (SELECT 1) SELECT * FROM a;")
    assert validate_sql("SELECT 'DB' = ANY(string_to_array(c, '; ')) FROM t")
    assert validate_sql("SELECT 'insert into x; for update' AS s, updated_at FROM t -- into")


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM mart.x",
        "SELECT set_config('role', 'app', true)",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT query_to_xml('select 1', true, false, '')",
        "SELECT pg_sleep(100)",
        "CREATE VIEW v AS SELECT 1",
        "SELECT * INTO scratch FROM raw.claims",
        "SELECT * INTO TEMP scratch FROM raw.claims",
        "WITH d AS (DELETE FROM mart.x RETURNING *) SELECT * FROM d",
        "WITH u AS (UPDATE mart.x SET a = 1 RETURNING *) SELECT 1",
        "WITH i AS (INSERT INTO mart.x VALUES (1) RETURNING *) SELECT 1",
        "SELECT * FROM raw.claims FOR UPDATE",
        "SELECT * FROM raw.claims FOR NO KEY UPDATE",
        "SELECT 1 FROM raw.claims for  share",
    ],
)
def test_rejects(sql):
    with pytest.raises(QueryError):
        validate_sql(sql)
