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
import json
import os
import subprocess
import sys

import pytest

from tests.system.ibis12.engines import ENGINES, ORACLE

if not os.environ.get("DVT_IBIS12_SYSTEM"):
    collect_ignore_glob = ["test_*.py"]  # run by tests/system/ibis12/run.sh only


def dvt(*args, check=True):
    """`data-validation <args>` in a subprocess, as a user runs it; its JSON output parsed."""
    result = subprocess.run([sys.executable, "-m", "data_validation", *args],
                            capture_output=True, text=True, timeout=900)
    if check and result.returncode != 0 and not result.stdout.strip().startswith("{"):
        raise AssertionError(f"data-validation {' '.join(args)} failed:\n{result.stderr[-3000:]}")
    return result


def dvt_json(*args) -> list:
    out = dvt(*args, "--format", "json").stdout
    start = out.find("{")
    parsed = json.loads(out[start:]) if start >= 0 else {}
    return list(parsed.values())


def _bootstrap_mssql():
    """SQL Server's dvt database, which `connections add` connects to: from master, outside a
    transaction (CREATE DATABASE refuses one)."""
    import pyodbc

    with pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};SERVER=mssql,1433;UID=sa;PWD=Dvt_test_pw1;"
        "TrustServerCertificate=yes", autocommit=True
    ) as con:
        con.execute("IF DB_ID('dvt') IS NULL CREATE DATABASE dvt")


def _seed(engine):
    from data_validation import clients, state_manager

    config = state_manager.StateManager().get_connection_config(engine.name)
    client = clients.get_data_client(config)
    for statement in engine.statements():
        result = client.raw_sql(statement)
        # a cursor is closed; DuckDB's raw_sql returns the connection itself
        if result is not getattr(client, "con", None) and hasattr(result, "close"):
            result.close()
    commit = getattr(getattr(client, "con", None), "commit", None)
    if commit:
        commit()
    client.disconnect()


@pytest.fixture(scope="session", autouse=True)
def engines(tmp_path_factory):
    """Every engine's DVT connection (through `connections add`) and its tables."""
    home = tmp_path_factory.mktemp("conn")
    os.environ["PSO_DV_CONN_HOME"] = str(home)
    _bootstrap_mssql()
    for engine in (ORACLE, *ENGINES.values()):
        dvt("connections", "add", "-c", engine.name, *engine.connection)
        _seed(engine)
    yield ENGINES
