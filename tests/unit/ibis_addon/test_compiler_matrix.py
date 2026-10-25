# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""What DVT's operations compile to on each engine (ibis 12, sqlglot dialects), compared without
case, quotes or spacing, so a fragment pins the SQL's meaning and not ibis's formatting."""

import re

import ibis
import pytest

# Import required in order to register DVT operations.
import third_party.ibis.ibis_addon.operations as operations

TABLE = ibis.table(
    {
        "s": "string",
        "b": "binary",
        "d": "decimal(10, 2)",
        "u": "decimal",
        "f": "float64",
        "ts": "timestamp",
        "bo": "boolean",
        "i": "int32",
    },
    name="t",
)


def _norm(sql: str) -> str:
    sql = re.sub(r"\s+", " ", re.sub(r'["`\[\]]', "", sql)).lower()
    return re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", sql))


def _sql(expr, dialect) -> str:
    return _norm(str(ibis.to_sql(expr, dialect=dialect)))


HEXDIGEST = {
    "bigquery": "to_hex(sha256(t0.s))",
    "postgres": "encode(sha256(convert_to(t0.s, 'utf8')), 'hex')",
    "mysql": "sha2(t0.s, '256')",
    "mssql": "lower(convert(char(64), hashbytes('sha2_256', convert(varchar(max), t0.s)), 2))",
    "impala": "sha2(t0.s, 256)",
    "databricks": "sha2(t0.s, 256)",
    "snowflake": "sha2(t0.s)",
    "oracle": "lower(standard_hash(convert(t0.s, 'utf8'), 'sha256'))",
    "duckdb": "sha256(t0.s)",
    "trino": "lower(to_hex(sha256(to_utf8(t0.s))))",
    "athena": "lower(to_hex(sha256(to_utf8(t0.s))))",
    "clickhouse": "lower(hex(sha256(t0.s)))",
    "exasol": "lower(hash_sha256(t0.s))",
    "flink": "sha256(t0.s)",
    "materialize": "encode(sha256(convert_to(t0.s, 'utf8')), 'hex')",
    "risingwave": "encode(sha256(convert_to(t0.s, 'utf8')), 'hex')",
    "datafusion": "encode(sha256(t0.s), 'hex')",
}

BINARY_LENGTH = {
    "bigquery": "length(t0.b)",
    "postgres": "length(t0.b)",
    "mysql": "length(t0.b)",
    "mssql": "cast(datalength(t0.b) as bigint)",
    "impala": "length(t0.b)",
    "databricks": "length(t0.b)",
    "snowflake": "length(t0.b)",
    "oracle": "dbms_lob.getlength(t0.b)",
}

DECIMAL_TO_STRING = {
    "oracle": "case when t0.d > 0 and t0.d < 1 then concat('0', to_char(t0.d))",
    # Postgres writes rtrim(x, '.') as TRIM(TRAILING '.' FROM x)
    "postgres": "trim(trailing '.' from to_char(t0.d, 'fm99999990.99'))",
    "mysql": "cast(t0.d as char) + 0",
    "mssql": "format(t0.d, '0.##')",
    "snowflake": "rtrim(to_char(t0.d, 'fm99999990.99'), '.')",
    "impala": "regexp_replace(regexp_replace(cast(t0.d as string), '([.][0-9]*?)0+$', '$1'), '[.]$', '')",
    "databricks": "regexp_replace(regexp_replace(cast(t0.d as string), '([.][0-9]*?)0+$', '$1'), '[.]$', '')",
    "trino": "if(cast(t0.d as varchar) like '%.%', trim(trailing '.' from trim(trailing '0' from cast(t0.d as varchar))), cast(t0.d as varchar))",
    "athena": "if(cast(t0.d as varchar) like '%.%', trim(trailing '.' from trim(trailing '0' from cast(t0.d as varchar))), cast(t0.d as varchar))",
    "clickhouse": "case when cast(t0.d as nullable(string)) like '%.%' then trim(trailing '.' from trim(trailing '0' from cast(t0.d as nullable(string))))",
    "exasol": "case when cast(t0.d as varchar(2000000)) like '%.%' then trim(trailing '.' from trim(trailing '0' from",
    "flink": "if(cast(t0.d as string) like '%.%', trim(trailing '.' from trim(trailing '0' from cast(t0.d as string)))",
    "druid": "case when cast(t0.d as varchar) like '%.%' then trim(trailing '.' from trim(trailing '0' from cast(t0.d as varchar)))",
    "materialize": "trim(trailing '.' from to_char(t0.d, 'fm99999990.99'))",
}

BINARY_TO_STRING = {
    "oracle": "lower(rawtohex(t0.b))",
    "bigquery": "to_hex(t0.b)",
    "postgres": "encode(t0.b, 'hex')",
    "mysql": "lower(hex(t0.b))",
    "mssql": "lower(convert(varchar(max), t0.b, 2))",
    "snowflake": "hex_encode(t0.b, 0)",
    "impala": "lower(hex(t0.b))",
    "databricks": "lower(hex(t0.b))",
    "trino": "lower(to_hex(t0.b))",
    "clickhouse": "lower(hex(t0.b))",
    "sqlite": "lower(hex(t0.b))",
    "datafusion": "encode(t0.b, 'hex')",
    "materialize": "encode(t0.b, 'hex')",
}

EPOCH_SECONDS = {
    "bigquery": "unix_seconds(cast(t0.ts as timestamp))",
    "oracle": "cast((cast(t0.ts as date) - to_date('1970-01-01', 'yyyy-mm-dd')) * 86400 as number(38, 0))",
    "postgres": "cast(extract(epoch from date_trunc('second', t0.ts)) as bigint)",
    "mssql": "cast(datediff_big(s, cast('1970-01-01 00:00:00' as datetime2), cast(t0.ts as datetime2)) as bigint)",
}

RSTRIP = {
    "oracle": "rtrim(t0.s, ' ' || chr(9) || chr(10) || chr(13) || chr(11) || chr(12))",
    "impala": "trim(trailing ' ' || chr(9) || chr(10) || chr(13) || chr(11) || chr(12) from t0.s)",
    "databricks": "trim(trailing ' ' || chr(9) || chr(10) || chr(13) || chr(11) || chr(12) from t0.s)",
    "mssql": "rtrim(convert(nvarchar(max), t0.s))",
}


@pytest.mark.parametrize("dialect,fragment", HEXDIGEST.items())
def test_hexdigest(dialect, fragment):
    assert _norm(fragment) in _sql(TABLE.s.hexdigest("sha256").name("h"), dialect)


@pytest.mark.parametrize("dialect,fragment", BINARY_LENGTH.items())
def test_binary_length(dialect, fragment):
    assert _norm(fragment) in _sql(TABLE.b.byte_length().name("n"), dialect)


@pytest.mark.parametrize("dialect,fragment", DECIMAL_TO_STRING.items())
def test_a_decimal_to_string_has_no_trailing_zeros_nor_lost_leading_zero(dialect, fragment):
    assert _norm(fragment) in _sql(TABLE.d.cast("string").name("x"), dialect)


@pytest.mark.parametrize("dialect,fragment", BINARY_TO_STRING.items())
def test_a_binary_to_string_is_its_lower_case_hex(dialect, fragment):
    assert _norm(fragment) in _sql(TABLE.b.cast("string").name("x"), dialect)


@pytest.mark.parametrize("dialect,fragment", EPOCH_SECONDS.items())
def test_epoch_seconds(dialect, fragment):
    assert _norm(fragment) in _sql(TABLE.ts.epoch_seconds().name("x"), dialect)


@pytest.mark.parametrize("dialect,fragment", RSTRIP.items())
def test_rstrip_strips_every_whitespace_character(dialect, fragment):
    assert _norm(fragment) in _sql(TABLE.s.rstrip().name("x"), dialect)


@pytest.mark.parametrize("dialect", ["bigquery", "impala", "databricks"])
def test_strftime_reads_a_timestamp_as_it_is(dialect):
    sql = _sql(TABLE.ts.strftime("%Y-%m-%d %H:%M:%S").name("x"), dialect)
    expected = {
        "bigquery": "format_datetime('%e4y-%m-%d %t', datetime(t0.ts))",
        "impala": "date_format(t0.ts, 'yyyy-mm-dd hh:mm:ss')",
        "databricks": "date_format(t0.ts, 'yyyy-mm-dd hh:mm:ss')",
    }[dialect]
    assert expected in sql


def test_a_raw_sql_filter_is_taken_as_it_is():
    sql = _sql(TABLE.filter(operations.compile_raw_sql(TABLE, "s = 'x'")).count(), "oracle")
    assert "where (s = 'x')" in sql


@pytest.mark.parametrize("dialect", ["mssql"])
def test_a_single_column_concat_is_the_column(dialect):
    sql = _sql(ibis.literal("").join([TABLE.s]).name("x"), dialect)
    assert "concat(" not in sql


def test_an_integer_sum_and_mean_on_sql_server_avoid_int_overflow_and_truncation():
    assert "sum(cast(t0.i as bigint))" in _sql(TABLE.i.sum().name("x"), "mssql")
    assert "avg(cast(t0.i as float))" in _sql(TABLE.i.mean().name("x"), "mssql")


@pytest.mark.parametrize("dialect,expected", [
    ("exasol", "to_char(t0.ts, 'yyyy-mm-dd hh24:mi:ss')"),
    ("druid", "time_format(t0.ts, 'yyyy-mm-dd hh:mm:ss')"),
    # MySQL-like formats: minutes are %i, %M is a month's name
    ("trino", "date_format(t0.ts, '%y-%m-%d %t')"),  # %T: hh:mm:ss, sqlglot's form of %H:%i:%s
    ("clickhouse", "formatdatetime(t0.ts, '%y-%m-%d %h:%i:%s')"),
])
def test_strftime_on_engines_without_ibis_own(dialect, expected):
    assert expected in _sql(TABLE.ts.strftime("%Y-%m-%d %H:%M:%S").name("x"), dialect)


def test_a_strftime_token_dvt_doesnt_write_is_refused_not_mistranslated():
    with pytest.raises(NotImplementedError, match="%j"):
        _sql(TABLE.ts.strftime("%Y-%j").name("x"), "exasol")


def test_singlestoredb_has_mysqls_rules():
    from ibis.backends.sql.compilers.singlestoredb import compiler

    expr = TABLE.select(h=TABLE.s.hexdigest("sha256"), x=TABLE.b.cast("string"))
    sql = _norm(compiler.to_sqlglot(expr).sql(compiler.dialect))
    assert "sha2(t0.s, '256')" in sql and "lower(hex(t0.b))" in sql


def test_a_float_on_trino_is_its_plain_text_not_scientific():
    sql = _sql(TABLE.f.cast("string").name("x"), "trino")
    assert "format('%s', t0.f)" in sql


def test_sql_server_2019_hashes_text_through_a_utf8_collation():
    from third_party.ibis.ibis_addon.operations import MSSQLUTF8Compiler

    compiler = MSSQLUTF8Compiler()
    sql = _norm(compiler.to_sqlglot(TABLE.select(h=TABLE.s.hexdigest("sha256"))).sql(
        compiler.dialect))
    assert "convert(varchar(max), t0.s collate latin1_general_100_ci_as_sc_utf8)" in sql
    assert "collate" not in _sql(TABLE.s.hexdigest("sha256").name("h"), "mssql")


def test_a_text_cast_on_sql_server_keeps_unicode():
    """A VARCHAR keeps only the database code page's characters (Zażółć -> Zazólc)."""
    not_null = ibis.table({"s": "!string"}, name="t")  # DVT's cast of a NOT NULL column
    assert "cast(t0.s as nvarchar(max))" in _sql(not_null.s.cast("string").name("x"), "mssql")
    assert "cast(t0.i as nvarchar(max))" in _sql(TABLE.i.cast("string").name("x"), "mssql")


def test_a_null_float_on_trino_stays_null():
    """format('%s', NULL) is the text 'null' on Trino: a NULL double keeps NULL."""
    sql = _sql(TABLE.f.cast("string").name("x"), "trino")
    assert "if(t0.f is null, null," in sql
