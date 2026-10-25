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
"""The engines of DVT's ibis 12 system tests (compose.yml): each one's DVT connection, its
`dvt_core` table in its own types, and the SQL that loads it. Every engine holds the same rows;
`dvt_core_chg` has one cell changed (col_dec of id 2), which every check must catch on id 2."""

import dataclasses
import datetime as dt
from decimal import Decimal

PASSWORD = "dvt_test_pw1"

# id, col_int, col_dec, col_float, col_str, col_char, col_date, col_ts
ROWS = [
    (1, 1, Decimal("1234.50"), 1.5, "abc", "ab", dt.date(2026, 10, 1),
     dt.datetime(2026, 10, 1, 12, 34, 56)),
    (2, -7, Decimal("-0.01"), -2.25, "Zażółć", "x", dt.date(1999, 12, 31),
     dt.datetime(1999, 12, 31, 23, 59, 59)),
    (3, None, None, None, None, None, None, None),
    (4, 12345678901, Decimal("0.50"), 0.0, "it's", "yy", dt.date(2000, 2, 29),
     dt.datetime(2000, 2, 29, 0, 0, 0)),
]
COLUMNS = ["id", "col_int", "col_dec", "col_float", "col_str", "col_char", "col_date", "col_ts"]
CHANGED = {"id": 2, "col_dec": Decimal("-0.02")}


@dataclasses.dataclass
class Engine:
    name: str
    connection: list  # `data-validation connections add` arguments after the name
    schema: str  # the -tbls schema of its tables
    types: list  # its type of each of COLUMNS
    setup: list = dataclasses.field(default_factory=list)  # statements before the tables
    table_suffix: str = ""  # after the column list (ClickHouse's ENGINE)
    literal: object = None  # value -> SQL literal, beyond the common forms
    name_case: str = "lower"  # how its tables are named (Oracle: upper)

    def lit(self, value) -> str:
        own = self.literal(value) if self.literal else None
        if own is not None:
            return own
        if value is None:
            return "NULL"
        if isinstance(value, str):
            return "'" + value.replace("'", "''") + "'"
        if isinstance(value, dt.datetime):
            return f"TIMESTAMP '{value:%Y-%m-%d %H:%M:%S}'"
        if isinstance(value, dt.date):
            return f"DATE '{value:%Y-%m-%d}'"
        return str(value)

    def table(self, name: str) -> str:
        return name.upper() if self.name_case == "upper" else name

    def statements(self) -> list:
        out = list(self.setup)
        for table, rows in (("dvt_core", ROWS), ("dvt_core_chg", _changed(ROWS))):
            qualified = f"{self.schema}.{self.table(table)}"
            columns = ", ".join(f"{c} {t}" for c, t in zip(COLUMNS, self.types))
            out.append(f"DROP TABLE IF EXISTS {qualified}")
            out.append(f"CREATE TABLE {qualified} ({columns}){self.table_suffix}")
            for row in rows:
                out.append(f"INSERT INTO {qualified} VALUES ({', '.join(map(self.lit, row))})")
        return out


def _changed(rows):
    return [
        tuple(CHANGED["col_dec"] if (r[0] == CHANGED["id"] and c == "col_dec") else v
              for c, v in zip(COLUMNS, r))
        for r in rows
    ]


def _mssql_literal(value):
    if isinstance(value, str):
        return "N'" + value.replace("'", "''") + "'"
    if isinstance(value, dt.datetime):
        return f"CAST('{value:%Y-%m-%d %H:%M:%S}' AS DATETIME2(6))"
    if isinstance(value, dt.date):
        return f"CAST('{value:%Y-%m-%d}' AS DATE)"
    return None


def _clickhouse_literal(value):
    if isinstance(value, dt.datetime):
        return f"toDateTime64('{value:%Y-%m-%d %H:%M:%S}', 6)"
    if isinstance(value, dt.date):
        return f"toDate('{value:%Y-%m-%d}')"
    if isinstance(value, Decimal):
        return f"toDecimal64('{value}', 2)"
    return None


ORACLE = Engine(
    "oracle",
    ["Oracle", "--host", "oracle", "--port", "1521", "--user", "SYSTEM", "--password", PASSWORD,
     "--database", "FREEPDB1"],
    "DVT",
    ["NUMBER(10) PRIMARY KEY", "NUMBER(19)", "NUMBER(10,2)", "BINARY_DOUBLE",
     "VARCHAR2(30 CHAR)", "CHAR(5 CHAR)", "DATE", "TIMESTAMP(6)"],
    setup=[f"CREATE USER IF NOT EXISTS dvt IDENTIFIED BY {PASSWORD} QUOTA UNLIMITED ON users"],
    name_case="upper",
)

ENGINES = {
    "mssql": Engine(
        "mssql",
        ["MSSQL", "--host", "mssql", "--port", "1433", "--user", "sa", "--password",
         "Dvt_test_pw1", "--database", "dvt",
         "--query", '{"driver": "ODBC Driver 18 for SQL Server", "TrustServerCertificate": "yes"}'],
        "dbo",
        ["INT PRIMARY KEY", "BIGINT", "DECIMAL(10,2)", "FLOAT", "NVARCHAR(30)", "NCHAR(5)",
         "DATE", "DATETIME2(6)"],
        literal=_mssql_literal,
    ),
    "postgres": Engine(
        "postgres",
        ["Postgres", "--host", "postgres", "--port", "5432", "--user", "postgres",
         "--password", PASSWORD, "--database", "dvt"],
        "public",
        ["INTEGER PRIMARY KEY", "BIGINT", "NUMERIC(10,2)", "DOUBLE PRECISION",
         "VARCHAR(30)", "CHAR(5)", "DATE", "TIMESTAMP(6)"],
    ),
    "mysql": Engine(
        "mysql",
        ["MySQL", "--host", "mysql", "--port", "3306", "--user", "root", "--password",
         PASSWORD, "--database", "dvt"],
        "dvt",
        ["INT PRIMARY KEY", "BIGINT", "DECIMAL(10,2)", "DOUBLE", "VARCHAR(30)", "CHAR(5)",
         "DATE", "DATETIME(6)"],
    ),
    "trino": Engine(
        "trino",
        ["Trino", "--host", "trino", "--port", "8080", "--user", "dvt", "--catalog", "memory",
         "--schema", "dvt"],
        "dvt",
        ["INTEGER", "BIGINT", "DECIMAL(10,2)", "DOUBLE", "VARCHAR(30)", "CHAR(5)", "DATE",
         "TIMESTAMP(6)"],
        setup=["CREATE SCHEMA IF NOT EXISTS memory.dvt"],
    ),
    "clickhouse": Engine(
        "clickhouse",
        ["ClickHouse", "--host", "clickhouse", "--port", "8123", "--user", "dvt",
         "--password", PASSWORD, "--database", "dvt"],
        "dvt",
        ["Int32", "Nullable(Int64)", "Nullable(Decimal(10,2))", "Nullable(Float64)",
         "Nullable(String)", "Nullable(String)", "Nullable(Date)", "Nullable(DateTime64(6))"],
        table_suffix=" ENGINE = MergeTree ORDER BY id",
        literal=_clickhouse_literal,
    ),
    "duckdb": Engine(
        "duckdb",
        ["DuckDB", "--database", "/tmp/dvt_ibis12.duckdb"],
        "main",
        ["INTEGER PRIMARY KEY", "BIGINT", "DECIMAL(10,2)", "DOUBLE", "VARCHAR(30)",
         "CHAR(5)", "DATE", "TIMESTAMP"],
    ),
}
