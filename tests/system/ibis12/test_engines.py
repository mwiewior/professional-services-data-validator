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
"""DVT on ibis 12 against each engine on Docker (tests/system/ibis12/run.sh): the schema, column
and row validations pass on equal tables and fail on a changed cell, on its key only, with the
engine on both sides and with Oracle as the source."""

import pytest

from tests.system.ibis12.conftest import dvt_json
from tests.system.ibis12.engines import CHANGED, ENGINES, ORACLE

PAIRS = [(name, name) for name in ENGINES] + [("oracle", name) for name in ENGINES]
NUMBERS = "col_int,col_dec,col_float"
ORDERED = "col_int,col_dec,col_float,col_date,col_ts"


def _engine(name):
    return ORACLE if name == "oracle" else ENGINES[name]


def _tables(source, target, table="dvt_core", target_table=None):
    s, t = _engine(source), _engine(target)
    return (f"{s.schema}.{s.table(table)}="
            f"{t.schema}.{t.table(target_table or table)}")


def _column(source, target, **kw):
    return dvt_json("validate", "column", "-sc", source, "-tc", target,
                    "-tbls", _tables(source, target, **kw), "--count", "*",
                    "--sum", NUMBERS, "--min", ORDERED, "--max", ORDERED)


def _row(source, target, **kw):
    return dvt_json("validate", "row", "-sc", source, "-tc", target,
                    "-tbls", _tables(source, target, **kw), "--primary-keys", "id",
                    "--hash", "*")


def _failures(rows):
    return [r for r in rows if r["validation_status"] != "success"]


@pytest.mark.parametrize("source,target", PAIRS)
def test_equal_tables_pass_the_column_check(source, target):
    rows = _column(source, target)
    assert rows and not _failures(rows), _failures(rows)


@pytest.mark.parametrize("source,target", PAIRS)
def test_equal_tables_pass_the_row_check(source, target):
    rows = _row(source, target)
    assert len(rows) == 4 and not _failures(rows), _failures(rows)


@pytest.mark.parametrize("source,target", PAIRS)
def test_a_changed_cell_fails_the_column_check_on_its_column(source, target):
    failed = {r["validation_name"] for r in _failures(
        _column(source, target, target_table="dvt_core_chg"))}
    assert failed == {"sum__col_dec", "min__col_dec"}


@pytest.mark.parametrize("source,target", PAIRS)
def test_a_changed_cell_fails_the_row_check_on_its_key_only(source, target):
    failed = _failures(_row(source, target, target_table="dvt_core_chg"))
    assert [f["group_by_columns"] for f in failed] == [f'{{"id": "{CHANGED["id"]}"}}']


@pytest.mark.parametrize("name", list(ENGINES))
def test_an_engine_against_itself_passes_the_schema_check(name):
    rows = dvt_json("validate", "schema", "-sc", name, "-tc", name,
                    "-tbls", _tables(name, name))
    assert rows and not _failures(rows), _failures(rows)


# Oracle's types against SQL Server's for dvt_core, as a migration's allow-list declares them
ORACLE_MSSQL_PAIRS = ("!decimal(10,0):!int32,decimal(19,0):int64,string:string(30),"
                      "string:string(5),timestamp:timestamp(6)")


def test_oracle_against_sql_server_passes_the_schema_check_with_its_type_pairs():
    """The SQL Server + SSIS epic's pair (#184): every check passes on equal tables."""
    rows = dvt_json("validate", "schema", "-sc", "oracle", "-tc", "mssql",
                    "-tbls", _tables("oracle", "mssql"), "--allow-list", ORACLE_MSSQL_PAIRS)
    assert len(rows) == 8 and not _failures(rows), _failures(rows)


def test_without_its_type_pairs_the_schema_check_names_each_difference():
    rows = dvt_json("validate", "schema", "-sc", "oracle", "-tc", "mssql",
                    "-tbls", _tables("oracle", "mssql"))
    assert {r["source_column_name"].lower() for r in _failures(rows)} == {
        "id", "col_int", "col_str", "col_char", "col_ts"}
