# Copyright 2025 Google LLC
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

from unittest import mock

import pytest


class PgColumn:
    def __init__(
        self, name, type_code, display_size, internal_size, precision, scale, null_ok
    ):
        self.name = name
        self.type_code = type_code
        self.display_size = display_size
        self.internal_size = internal_size
        self.precision = precision
        self.scale = scale
        self.null_ok = null_ok


DVT_CORE_TYPES_CURS = (
    PgColumn("id", 23, None, 4, None, None, None),
    PgColumn("col_int8", 21, None, 2, None, None, None),
    PgColumn("col_int16", 21, None, 2, None, None, None),
    PgColumn("col_int32", 23, None, 4, None, None, None),
    PgColumn("col_int64", 20, None, 8, None, None, None),
    PgColumn("col_dec_20", 1700, None, 20, 20, 0, None),
    PgColumn("col_dec_38", 1700, None, 38, 38, 0, None),
    PgColumn("col_dec_10_2", 1700, None, 10, 10, 2, None),
    PgColumn("col_float32", 700, None, 4, None, None, None),
    PgColumn("col_float64", 701, None, 8, None, None, None),
    PgColumn("col_varchar_30", 1043, None, 30, None, None, None),
    PgColumn("col_char_2", 1042, None, 2, None, None, None),
    PgColumn("col_string", 25, None, -1, None, None, None),
    PgColumn("col_date", 1082, None, 4, None, None, None),
    PgColumn("col_datetime", 1114, None, 8, None, None, None),
    PgColumn("col_tstz", 1184, None, 8, None, None, None),
)


@pytest.fixture
def module_under_test():
    from third_party.ibis import ibis_postgres

    return ibis_postgres


def _connected(module_under_test, description=(), rows=()):
    """A backend whose psycopg connection is a mock: its cursor reports `description` and
    fetches `rows`; the cursor is returned for asserting on what ran."""
    cursor = mock.MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.description = description
    cursor.fetchall.return_value = list(rows)
    backend = module_under_test.Backend()
    backend.con = mock.Mock(cursor=mock.Mock(return_value=cursor))
    return backend, cursor


def test_import(module_under_test):
    assert module_under_test is not None


def test_raw_column_metadata_no_args(module_under_test):
    backend = module_under_test.Backend()
    with pytest.raises(AssertionError):
        _ = list(backend.raw_column_metadata(database=None, table=None, query=None))


TYPE_NAMES = [("integer",), ("smallint",), ("smallint",), ("integer",), ("bigint",),
              ("numeric",), ("numeric",), ("numeric",), ("real",), ("double precision",),
              ("character varying",), ("character",), ("text",), ("date",),
              ("timestamp without time zone",), ("timestamp with time zone",)]


def test_raw_column_metadata_core_types(module_under_test):
    backend, cursor = _connected(module_under_test, DVT_CORE_TYPES_CURS, TYPE_NAMES)
    raw_types = list(
        backend.raw_column_metadata(
            database="pso_data_validator", table="dvt_core_types"
        )
    )
    # Ensure we have 7 attributes, PostgreSQL's own type names among them.
    assert all(len(_) == 7 for _ in raw_types)
    assert raw_types[11] == ("col_char_2", "character", None, 2, None, None, None)
    assert backend.is_char_type_padded(raw_types[11][1:])
    first_sql = cursor.execute.call_args_list[0].args[0]
    assert first_sql == 'SELECT * FROM "pso_data_validator"."dvt_core_types" t0 LIMIT 0'


def test_raw_column_metadata_qry(module_under_test):
    backend, cursor = _connected(module_under_test, DVT_CORE_TYPES_CURS, TYPE_NAMES)
    raw_types = list(
        backend.raw_column_metadata(
            query="SELECT * FROM pso_data_validator.dvt_core_types"
        )
    )
    # Ensure we have 7 attributes.
    assert all(len(_) == 7 for _ in raw_types)
    assert cursor.execute.call_args_list[0].args[0] == (
        "SELECT * FROM (SELECT * FROM pso_data_validator.dvt_core_types) t0 LIMIT 0"
    )


def test_list_primary_key_columns(module_under_test):
    backend, cursor = _connected(module_under_test, rows=[("id",)])
    assert backend.list_primary_key_columns("app", "t") == ["id"]
    assert cursor.execute.call_args.args[1] == ("app.t",)
