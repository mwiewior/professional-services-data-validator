# Copyright 2023 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import json
from typing import Literal
from urllib.parse import urlparse

from third_party.ibis.ibis_mssql import DEFAULT_DRIVER_NAME
from third_party.ibis.ibis_mssql import Backend as MsSqlBackend


def mssql_connect(
    host: str = "localhost",
    user: str = None,
    password: str = None,
    port: int = 1433,
    database: str = None,
    url: str = None,
    driver: Literal["pyodbc"] = "pyodbc",
    odbc_driver: str = DEFAULT_DRIVER_NAME,
    query: str = None,
):
    """SQL Server through pyodbc. `query` is a JSON object of ODBC connection attributes
    (`{"TrustServerCertificate": "yes"}`, or its own `driver`); `url` a
    mssql://user:password@host:port/database URL in place of the other fields."""
    if driver != "pyodbc":
        raise NotImplementedError("pyodbc is currently the only supported driver")
    attributes = json.loads(query) if query else {}
    odbc_driver = attributes.pop("driver", None) or odbc_driver or DEFAULT_DRIVER_NAME
    if url is not None:
        parsed = urlparse(url)
        host, port = parsed.hostname or host, parsed.port or port
        user, password = parsed.username or user, parsed.password or password
        database = parsed.path.lstrip("/") or database
    backend = MsSqlBackend()
    backend.do_connect(
        host=host,
        port=int(port),
        user=user,
        password=password,
        database=database,
        driver=odbc_driver,
        **attributes,
    )
    return backend
