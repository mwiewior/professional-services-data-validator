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

from third_party.ibis.ibis_databricks import databricks_connect


def test_a_connection_creates_nothing_in_the_workspace():
    """ibis 12 creates a Unity Catalog volume per process on connect (for memtables, which DVT
    never sends to a target), named after the OS user, which a container's uid may not have."""
    con = mock.MagicMock()
    cursor = con.cursor.return_value.__enter__.return_value
    cursor.execute.return_value = cursor
    cursor.fetchall.return_value = [("axis",)]
    with mock.patch("databricks.sql.connect", return_value=con) as connect, mock.patch(
        "getpass.getuser", side_effect=KeyError("getpwuid(): uid not found: 501")
    ):
        databricks_connect(
            host="https://dbc-x.cloud.databricks.com/",
            http_path="/sql/1.0/warehouses/w",
            token="t",
            catalog="axis",
            schema="s",
        )

    statements = [c.args[0] for c in cursor.execute.call_args_list]
    assert not any("VOLUME" in s.upper() for s in statements), statements
    assert connect.call_args.kwargs["server_hostname"] == "dbc-x.cloud.databricks.com"
    assert connect.call_args.kwargs["catalog"] == "axis"
