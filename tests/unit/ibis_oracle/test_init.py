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


class oDbTypeMock:
    name: str = "DB_TYPE_MOCKTYPE"


DVT_CORE_TYPES_CURS = [
    ("ID", oDbTypeMock(), 9, None, 8, 0, 0),
    ("COL_INT8", oDbTypeMock(), 3, None, 2, 0, 1),
    ("COL_INT16", oDbTypeMock(), 5, None, 4, 0, 1),
    ("COL_INT32", oDbTypeMock(), 10, None, 9, 0, 1),
    ("COL_INT64", oDbTypeMock(), 19, None, 18, 0, 1),
    ("COL_DEC_20", oDbTypeMock(), 21, None, 20, 0, 1),
    ("COL_DEC_38", oDbTypeMock(), 39, None, 38, 0, 1),
    ("COL_DEC_10_2", oDbTypeMock(), 14, None, 10, 2, 1),
    ("COL_FLOAT32", oDbTypeMock(), 127, None, None, None, 1),
    ("COL_FLOAT64", oDbTypeMock(), 127, None, None, None, 1),
    ("COL_VARCHAR_30", oDbTypeMock(), 30, 30, None, None, 1),
    ("COL_CHAR_2", oDbTypeMock(), 2, 2, None, None, 1),
    ("COL_STRING", oDbTypeMock(), 4000, 4000, None, None, 1),
    ("COL_DATE", oDbTypeMock(), 23, None, None, None, 1),
    ("COL_DATETIME", oDbTypeMock(), 23, None, 0, 3, 1),
    ("COL_TSTZ", oDbTypeMock(), None, None, 0, 3, 1),
]


def get_module_under_test():
    try:
        from third_party.ibis import ibis_oracle
    except ModuleNotFoundError:
        # We don't install Oracle client for Github unit tests.
        # These tests will only complete when executed locally.
        ibis_oracle = None

    return ibis_oracle


@pytest.fixture
def module_under_test():
    return get_module_under_test()


@pytest.mark.skipif(not get_module_under_test(), reason="No Oracle driver")
def test_import(module_under_test):
    """Check that importing ibis_oracle does not throw exceptions (aside from ModuleNotFoundError)"""
    assert module_under_test is not None


@pytest.mark.skipif(not get_module_under_test(), reason="No Oracle driver")
def test_raw_column_metadata_no_args(module_under_test):
    backend = module_under_test.Backend()
    with pytest.raises(AssertionError):
        _ = list(backend.raw_column_metadata(database=None, table=None, query=None))


def _connected(module_under_test, description=None, rows=None):
    """A backend whose Oracle connection is a mock: each cursor reports `description` and
    fetches `rows`; the cursor is returned for asserting on what ran."""
    cursor = mock.MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.description = description
    cursor.fetchall.return_value = rows
    backend = module_under_test.Backend()
    backend.con = mock.Mock(cursor=mock.Mock(return_value=cursor))
    return backend, cursor


@pytest.mark.skipif(not get_module_under_test(), reason="No Oracle driver")
def test_raw_column_metadata_core_types(module_under_test):
    backend, cursor = _connected(module_under_test, DVT_CORE_TYPES_CURS)
    backend.list_tables = mock.Mock(return_value=["dvt_core_types"])

    raw_types = list(
        backend.raw_column_metadata(
            database="pso_data_validator", table="dvt_core_types"
        )
    )
    # Assert that the oracle prefix was removed from data types.
    assert all(_[1] == "MOCKTYPE" for _ in raw_types)
    # Ensure we have 7 attributes.
    assert all(len(_) == 7 for _ in raw_types)
    cursor.execute.assert_called_with(
        'SELECT * FROM "pso_data_validator"."dvt_core_types" t0 WHERE ROWNUM <= 1'
    )


@pytest.mark.skipif(not get_module_under_test(), reason="No Oracle driver")
def test_raw_column_metadata_qry(module_under_test):
    backend, cursor = _connected(module_under_test, DVT_CORE_TYPES_CURS)
    raw_types = list(
        backend.raw_column_metadata(
            query="SELECT * FROM pso_data_validator.dvt_core_types"
        )
    )
    # Assert that the oracle prefix was removed from data types.
    assert all(_[1] == "MOCKTYPE" for _ in raw_types)
    # Ensure we have 7 attributes.
    assert all(len(_) == 7 for _ in raw_types)
    cursor.execute.assert_called_with(
        "SELECT * FROM (SELECT * FROM pso_data_validator.dvt_core_types) t0 WHERE ROWNUM <= 1"
    )


SCHEMAS = [("SYS",), ("AUDSYS",), ("SYSTEM",), ("DBSNMP",), ("C##DS",), ("DVT_TEST",)]


@pytest.mark.skipif(not get_module_under_test(), reason="No Oracle driver")
def test_list_databases(module_under_test):
    """Test that list_databases excludes Oracle system schemas while preserving user and monitoring schemas."""
    backend, _cursor = _connected(module_under_test, rows=SCHEMAS)

    schemas = backend.list_databases()

    # SYS and AUDSYS should be filtered out.
    # SYSTEM, DBSNMP, C##DS, and DVT_TEST should remain.
    assert sorted(schemas) == sorted(["SYSTEM", "DBSNMP", "C##DS", "DVT_TEST"])


@pytest.mark.skipif(not get_module_under_test(), reason="No Oracle driver")
def test_list_databases_with_like(module_under_test):
    """Test that list_databases correctly filters schemas when a like pattern is provided."""
    backend, _cursor = _connected(module_under_test, rows=SCHEMAS)

    schemas = backend.list_databases(like=".*DVT.*")

    # Only DVT_TEST should match
    assert schemas == ["DVT_TEST"]


@pytest.mark.skipif(not get_module_under_test(), reason="No Oracle driver")
def test_get_schema_reads_oracle_types_as_dvt_does(module_under_test):
    """A DATE is a date and a NUMBER a decimal of its own precision, as on ibis 7."""
    import oracledb

    description = [
        ("ID", oracledb.DB_TYPE_NUMBER, 9, None, 8, 0, 0),
        ("AMT", oracledb.DB_TYPE_NUMBER, 14, None, 10, 2, 1),
        ("RATIO", oracledb.DB_TYPE_NUMBER, 127, None, 0, -127, 1),
        ("DAY", oracledb.DB_TYPE_DATE, 23, None, None, None, 1),
        ("TS", oracledb.DB_TYPE_TIMESTAMP, 23, None, 0, 6, 1),
        ("NAME", oracledb.DB_TYPE_VARCHAR, 30, 30, None, None, 1),
    ]
    backend, _cursor = _connected(module_under_test, description)
    backend.list_tables = mock.Mock(return_value=["T"])

    schema = backend.get_schema("t", database="APP")

    assert {name: str(typ) for name, typ in schema.items()} == {
        "ID": "!decimal(8, 0)",
        "AMT": "decimal(10, 2)",
        "RATIO": "decimal",
        "DAY": "date",
        "TS": "timestamp",
        "NAME": "string",
    }
