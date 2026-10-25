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

from third_party.ibis.ibis_impala.api import impala_connect


def test_every_cursor_runs_as_the_connections_user():
    """ibis 12 opens cursors without a user, so impyla asks the OS for one: in a container
    whose uid has no passwd entry that fails ('getpwuid(): uid not found')."""
    con = mock.MagicMock()
    with mock.patch("impala.dbapi.connect", return_value=con), mock.patch(
        "getpass.getuser", side_effect=KeyError("getpwuid(): uid not found: 501")
    ):
        backend = impala_connect(host="spark", user="axis")
        backend.con.cursor()

    assert [c.kwargs.get("user") for c in con.cursor.call_args_list] == ["axis"] * len(
        con.cursor.call_args_list
    )
    assert len(con.cursor.call_args_list) >= 2


def test_a_cursor_given_a_user_keeps_it():
    con = mock.MagicMock()
    with mock.patch("impala.dbapi.connect", return_value=con):
        backend = impala_connect(host="spark", user="axis")
        backend.con.cursor(user="other")
    assert con.cursor.call_args.kwargs["user"] == "other"


def test_connecting_leaves_no_cursor_open():
    """Every cursor of a connection shares its Thrift transport: one left open is closed whenever
    Python collects it, and its close RPC lands inside another cursor's, which then reads the
    wrong reply ("Invalid method name: 'CloseImpalaOperation'" on a Spark Thrift server)."""
    con = mock.MagicMock()
    cursors = []

    def cursor(**kwargs):
        cursors.append(mock.MagicMock())
        return cursors[-1]

    con.cursor.side_effect = cursor
    with mock.patch("impala.dbapi.connect", return_value=con):
        impala_connect(host="spark", user="axis")

    assert cursors and all(c.close.called for c in cursors)


def test_options_ibis_12_has_no_form_of_are_named_not_dropped(caplog):
    """ibis 12's Impala backend has no connection pool and no HDFS client: a connection that
    sets either says it is ignored, rather than dropping it silently."""
    con = mock.MagicMock()
    with mock.patch("impala.dbapi.connect", return_value=con):
        impala_connect(host="spark", user="axis", pool_size=4, hdfs_client="http://nn:9870")

    assert "pool_size" in caplog.text and "hdfs_client" in caplog.text


def test_default_options_log_nothing(caplog):
    con = mock.MagicMock()
    with mock.patch("impala.dbapi.connect", return_value=con):
        impala_connect(host="spark", user="axis")
    assert "ignored" not in caplog.text
