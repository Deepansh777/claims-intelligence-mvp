import pytest

from app.llm.schemas import QueryError
from app.services.analytics_sql import validate_sql


def test_allows_select_and_with():
    assert validate_sql("-- Raw fallback: x\nWITH a AS (SELECT 1) SELECT * FROM a;")
    assert validate_sql("SELECT 'DB' = ANY(string_to_array(c, '; ')) FROM t")


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM mart.x",
        "SELECT set_config('role', 'app', true)",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT query_to_xml('select 1', true, false, '')",
        "SELECT pg_sleep(100)",
    ],
)
def test_rejects(sql):
    with pytest.raises(QueryError):
        validate_sql(sql)
