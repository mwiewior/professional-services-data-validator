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

import datetime
import importlib
from unittest import mock

import ibis
import pandas
import pytest

from data_validation.query_builder.query_builder import FilterField


def test_filter_field_and():
    field1 = FilterField.equal_to("col1", "val1")
    field2 = FilterField.equal_to("col2", 2)
    and_field = FilterField.and_([field1, field2])

    assert and_field.expr == ibis.and_
    assert and_field.left == [field1, field2]


def test_filter_field_is_null():
    null_field = FilterField.is_null("col1")
    assert null_field.expr == ibis.expr.types.ColumnExpr.isnull
    assert null_field.left_field == "col1"


def test_composite_isin_tuple_in_path():
    mock_client = mock.MagicMock()
    mock_client.name = "postgres"
    mock_client.dvt_tuple_in_supported.return_value = True

    df = pandas.DataFrame({"col1": ["a", "b"], "col2": [1, 2]})
    ff = FilterField.composite_isin(mock_client, ["col1", "col2"], df)

    assert ff.expr == "tuple_in"
    assert ff.left == ["col1", "col2"]
    assert ff.right == [("a", 1), ("b", 2)]


def test_composite_isin_or_of_ands_fallback():
    mock_client = mock.MagicMock()
    mock_client.name = "mssql"
    mock_client.dvt_tuple_in_supported.return_value = False

    df = pandas.DataFrame({"col1": ["a", "b"], "col2": [1, None]})
    ff = FilterField.composite_isin(mock_client, ["col1", "col2"], df)

    assert ff.expr == ibis.or_
    assert len(ff.left) == 2

    # First row: col1='a' AND col2=1
    row1_and = ff.left[0]
    assert row1_and.expr == ibis.and_
    assert row1_and.left[0].left_field == "col1"
    assert row1_and.left[0].right == "a"
    assert row1_and.left[1].left_field == "col2"
    assert row1_and.left[1].right == 1

    # Second row: col1='b' AND col2 IS NULL
    row2_and = ff.left[1]
    assert row2_and.expr == ibis.and_
    assert row2_and.left[0].left_field == "col1"
    assert row2_and.left[0].right == "b"
    assert row2_and.left[1].expr == ibis.expr.types.ColumnExpr.isnull
    assert row2_and.left[1].left_field == "col2"


@mock.patch("data_validation.clients.get_max_in_list_size", return_value=2)
def test_composite_isin_chunking(mock_get_max_in):
    mock_client = mock.MagicMock()
    mock_client.name = "teradata"
    mock_client.dvt_tuple_in_supported.return_value = False

    df = pandas.DataFrame({"col1": ["a", "b", "c", "d", "e"], "col2": [1, 2, 3, 4, 5]})
    ff = FilterField.composite_isin(mock_client, ["col1", "col2"], df)

    assert ff.expr == ibis.or_
    # Chunked into sub-batches of 2
    assert len(ff.left) == 3
    for sub_batch in ff.left:
        assert sub_batch.expr == ibis.or_


@mock.patch("data_validation.clients.get_max_in_list_size", return_value=2)
def test_composite_isin_tuple_in_chunking(mock_get_max_in):
    mock_client = mock.MagicMock()
    mock_client.name = "postgres"
    mock_client.dvt_tuple_in_supported.return_value = True

    df = pandas.DataFrame({"col1": ["a", "b", "c", "d", "e"], "col2": [1, 2, 3, 4, 5]})
    ff = FilterField.composite_isin(mock_client, ["col1", "col2"], df)

    assert ff.expr == ibis.or_
    # Chunked into sub-batches of 2
    assert len(ff.left) == 3
    for sub_batch in ff.left:
        assert sub_batch.expr == "tuple_in"


@pytest.mark.parametrize(
    "module,supported",
    [
        ("third_party.ibis.ibis_oracle", True),
        ("third_party.ibis.ibis_bigquery", True),
        ("third_party.ibis.ibis_databricks", True),
        ("third_party.ibis.ibis_mssql", False),
        ("third_party.ibis.ibis_postgres", True),
        ("third_party.ibis.ibis_mysql", True),
        ("third_party.ibis.ibis_snowflake", True),
    ],
)
def test_backend_class_tuple_in_supported(module, supported):
    """Each DVT backend says whether its SQL has tuple IN; a backend whose driver isn't
    installed here is skipped."""
    try:
        backend_class = importlib.import_module(module).Backend
    except ImportError as exc:
        pytest.skip(f"{module}: {exc}")
    assert backend_class().dvt_tuple_in_supported() is supported


def test_filter_field_large_or_compilation():
    """Verify that compiling a large OR tree doesn't raise RecursionError.
    This ensures our balanced binary tree mitigation works."""
    table = ibis.table([("a", "int64"), ("b", "int64")], name="my_table")

    # 1000 items would typically trigger recursion error in sqlglot if parsed linearly
    eq_filters = []
    for i in range(1000):
        # We simulate the fallback row condition: (a=i AND b=i)
        f = FilterField.and_(
            [FilterField.equal_to("a", i), FilterField.equal_to("b", i)]
        )
        eq_filters.append(f)

    large_or = FilterField.or_(eq_filters)

    try:
        # Compilation should succeed via balanced binary tree
        compiled = large_or.compile(table)
        assert compiled is not None
    except RecursionError:
        import pytest

        pytest.fail("RecursionError encountered while compiling large OR condition.")


def test_compile_tuple_in_timestamps_and_dates():
    df = pandas.DataFrame(
        {
            "id": [1, 2, 3],
            "ts": [
                pandas.Timestamp("2026-08-04 07:12:44"),
                datetime.date(2026, 8, 4),
                None,
            ],
        }
    )

    for client_name in ["postgres", "oracle", "mssql"]:
        mock_client = mock.MagicMock()
        mock_client.name = client_name
        mock_client.dvt_tuple_in_supported.return_value = True

        ff = FilterField.composite_isin(mock_client, ["id", "ts"], df)
        table = ibis.table([("id", "int64"), ("ts", "timestamp")], name="t")
        compiled = ff.compile(table)
        sql_str = str(compiled)

        if client_name == "oracle":
            assert (
                "TO_TIMESTAMP('2026-08-04 07:12:44.000000', 'YYYY-MM-DD HH24:MI:SS.FF6')"
                in sql_str
            )
            assert "TO_DATE('2026-08-04', 'YYYY-MM-DD')" in sql_str
            assert "NULL" in sql_str
        else:
            assert "'2026-08-04 07:12:44'" in sql_str
            assert "'2026-08-04'" in sql_str
            assert "NULL" in sql_str
