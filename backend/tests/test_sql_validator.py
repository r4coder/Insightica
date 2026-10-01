import pytest

from app.tools.sql_validator import SQLValidationError, validate_sql, wrap_with_limit

TABLES = ["sales_ab12cd34"]
T = "sales_ab12cd34"


def ok(sql):
    return validate_sql(sql, TABLES)


def bad(sql):
    with pytest.raises(SQLValidationError):
        validate_sql(sql, TABLES)


def test_simple_select_allowed():
    assert ok(f"SELECT region, SUM(revenue) FROM {T} GROUP BY region ORDER BY 2 DESC;").endswith("DESC")


def test_cte_and_window_allowed():
    ok(f"WITH q AS (SELECT date_trunc('quarter', order_date) AS q, SUM(revenue) AS r FROM {T} GROUP BY 1) "
       f"SELECT q, r, r / NULLIF(LAG(r) OVER (ORDER BY q), 0) - 1 AS pct FROM q")


def test_join_and_subquery_allowed():
    ok(f"SELECT a.region FROM {T} a JOIN (SELECT region FROM {T} GROUP BY region) b ON a.region = b.region")


def test_extract_from_is_not_a_table_reference():
    ok(f"SELECT EXTRACT(year FROM order_date) AS y, COUNT(*) FROM {T} GROUP BY 1")
    ok(f"SELECT * FROM {T} WHERE region IS DISTINCT FROM 'West'")


def test_quoted_table_allowed_and_main_schema():
    ok(f'SELECT 1 FROM "{T}"')
    ok(f"SELECT 1 FROM main.{T}")


@pytest.mark.parametrize("sql", [
    "DROP TABLE x", f"DELETE FROM {T}", f"UPDATE {T} SET revenue = 0", f"INSERT INTO {T} VALUES (1)",
    f"ALTER TABLE {T} ADD COLUMN x INT", f"CREATE TABLE t AS SELECT 1", f"TRUNCATE {T}",
])
def test_ddl_dml_rejected(sql):
    bad(sql)


def test_multiple_statements_rejected():
    bad(f"SELECT 1 FROM {T}; DROP TABLE {T}")
    bad(f"SELECT 1 FROM {T}; SELECT 2 FROM {T}")


def test_non_select_rejected():
    bad("PRAGMA database_list")
    bad("COPY (SELECT 1) TO 'x.csv'")
    bad("ATTACH 'x.db'")
    bad("")


def test_file_access_rejected():
    bad("SELECT * FROM read_csv('/etc/passwd')")
    bad("SELECT * FROM 'secret.csv'")
    bad(f"SELECT * FROM {T}, read_parquet('x.parquet')")
    bad("SELECT * FROM parquet_scan('x')")


def test_unknown_or_system_tables_rejected():
    bad("SELECT * FROM other_table")
    bad("SELECT * FROM information_schema.tables")
    bad("SELECT * FROM duckdb_tables()")
    bad(f"SELECT * FROM {T} JOIN secrets ON 1=1")
    bad(f"SELECT * FROM {T}, other")


def test_keywords_in_strings_and_quoted_identifiers_are_fine():
    ok(f"SELECT * FROM {T} WHERE product = 'drop table; delete'")
    ok(f'SELECT "delete", "update" FROM {T}')


def test_comments_stripped_and_cannot_hide_statements():
    assert "--" not in ok(f"SELECT 1 FROM {T} -- trailing note")
    bad(f"SELECT 1 FROM {T} /* x */; DROP TABLE {T}")


def test_unbalanced_and_unterminated():
    bad(f"SELECT (1 FROM {T}")
    bad(f"SELECT 'abc FROM {T}")


def test_limit_wrapper_fetches_one_extra_row():
    assert "LIMIT 501" in wrap_with_limit("SELECT 1", 500)
