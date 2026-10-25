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
from unittest import mock

import pytest

pytest.importorskip("pyodbc", exc_type=ImportError)  # needs unixODBC; runs in the Docker runner


def _connected(major_version: str):
    from third_party.ibis.ibis_mssql import Backend

    cursor = mock.MagicMock()
    cursor.fetchone.return_value = (major_version,)
    backend = Backend()
    backend.con = mock.MagicMock()
    backend.con.cursor.return_value = cursor
    backend._post_connect()
    return backend


def test_sql_server_2019_hashes_text_as_utf8():
    """SQL Server 2019 (major version 15) has a UTF-8 collation: a hash reads text as its UTF-8
    bytes, as Oracle's does."""
    from third_party.ibis.ibis_addon.operations import MSSQLUTF8Compiler

    assert isinstance(_connected("15").compiler, MSSQLUTF8Compiler)


def test_an_older_sql_server_keeps_its_code_page():
    from third_party.ibis.ibis_addon.operations import MSSQLUTF8Compiler

    assert not isinstance(_connected("14").compiler, MSSQLUTF8Compiler)


def test_mssql_connect_passes_odbc_attributes_and_its_driver():
    from third_party.ibis.ibis_mssql.api import mssql_connect

    with mock.patch("pyodbc.connect") as connect, mock.patch(
        "third_party.ibis.ibis_mssql.Backend._post_connect"
    ):
        mssql_connect(host="db", user="sa", password="p", database="dvt",
                      query='{"driver": "ODBC Driver 18 for SQL Server", "TrustServerCertificate": "yes"}')
    kwargs = connect.call_args.kwargs
    assert kwargs["driver"] == "ODBC Driver 18 for SQL Server"
    assert kwargs["TrustServerCertificate"] == "yes" and kwargs["server"] == "db,1433"
