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
"""DVT's connections to ibis 12's other engines: DVT's text fields reach ibis's connect typed,
and each connection type is one DVT's CLI and clients know."""

from unittest import mock

import pytest

from data_validation import cli_tools, clients, consts
from third_party.ibis import ibis_engines

NEW_TYPES = [
    consts.SOURCE_TYPE_ATHENA, consts.SOURCE_TYPE_CLICKHOUSE, consts.SOURCE_TYPE_DATAFUSION,
    consts.SOURCE_TYPE_DRUID, consts.SOURCE_TYPE_DUCKDB, consts.SOURCE_TYPE_EXASOL,
    consts.SOURCE_TYPE_FLINK, consts.SOURCE_TYPE_MATERIALIZE, consts.SOURCE_TYPE_POLARS,
    consts.SOURCE_TYPE_PYSPARK, consts.SOURCE_TYPE_RISINGWAVE,
    consts.SOURCE_TYPE_SINGLESTOREDB, consts.SOURCE_TYPE_SQLITE, consts.SOURCE_TYPE_TRINO,
]


@pytest.mark.parametrize("source_type", NEW_TYPES)
def test_every_new_type_has_cli_fields_matching_its_connect(source_type):
    import inspect

    connect = clients.CLIENT_LOOKUP[source_type]
    fields = [f[0] for f in cli_tools.CONNECTION_SOURCE_FIELDS[source_type]]
    params = list(inspect.signature(connect).parameters)
    assert fields and set(fields) <= set(params), (fields, params)


def test_duckdb_reads_a_database_file(tmp_path):
    import duckdb

    path = tmp_path / "t.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE SCHEMA app; CREATE TABLE app.t AS SELECT 1 AS id")
    client = clients.get_data_client(
        {consts.SOURCE_TYPE: consts.SOURCE_TYPE_DUCKDB, "database": str(path),
         "read_only": "true"}
    )
    table = clients.get_ibis_table(client, "app", "t")
    assert client.execute(table.count()) == 1


def test_sqlite_reads_a_database_file(tmp_path):
    import sqlite3

    path = tmp_path / "t.db"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE t AS SELECT 1 AS id")
    client = clients.get_data_client(
        {consts.SOURCE_TYPE: consts.SOURCE_TYPE_SQLITE, "database": str(path)}
    )
    assert client.execute(clients.get_ibis_table(client, None, "t").count()) == 1


@pytest.mark.parametrize("source_type", [consts.SOURCE_TYPE_POLARS, consts.SOURCE_TYPE_DATAFUSION])
def test_an_in_process_engine_reads_its_tables_from_files(tmp_path, source_type):
    pytest.importorskip(source_type.lower())
    (tmp_path / "a.csv").write_text("id,name\n1,x\n2,y\n")
    client = clients.get_data_client(
        {consts.SOURCE_TYPE: source_type, "tables": f"a={tmp_path / 'a.csv'}"}
    )
    assert client.execute(clients.get_ibis_table(client, None, "a").count()) == 2


def test_trino_gets_typed_arguments_and_basic_auth_over_https():
    with mock.patch("ibis.trino.connect") as connect:
        ibis_engines.trino_connect(host="tr", port="8443", user="u", password="p",
                                   catalog="memory", schema="app")
    kwargs = connect.call_args.kwargs
    assert kwargs["port"] == 8443 and kwargs["database"] == "memory"
    assert kwargs["schema"] == "app" and kwargs["http_scheme"] == "https"
    assert kwargs["auth"] is not None


def test_trino_without_a_password_sends_no_auth():
    with mock.patch("ibis.trino.connect") as connect:
        ibis_engines.trino_connect(host="tr")
    assert "auth" not in connect.call_args.kwargs
    assert connect.call_args.kwargs["port"] == 8080


def test_clickhouse_reads_secure_as_a_flag():
    with mock.patch("ibis.clickhouse.connect") as connect:
        ibis_engines.clickhouse_connect(host="ch", port="8443", secure="true")
    assert connect.call_args.kwargs["secure"] is True
    assert connect.call_args.kwargs["port"] == 8443


def test_a_file_of_unknown_kind_is_refused(tmp_path):
    with pytest.raises(KeyError):
        ibis_engines._with_files(mock.Mock(), f"a={tmp_path / 'a.xlsx'}")
