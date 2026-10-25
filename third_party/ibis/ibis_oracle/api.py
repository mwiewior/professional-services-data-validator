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
from typing import Literal

import oracledb  # NOQA fail early if the driver is missing

from data_validation.util import dvt_config_string_to_dict
from third_party.ibis.ibis_oracle import Backend as OracleBackend


def oracle_connect(
    host: str = "localhost",
    user: str = None,
    password: str = None,
    port: int = 1521,
    database: str = None,
    protocol: str = "TCP",
    thick_mode: bool = False,
    driver: Literal["oracledb"] = "oracledb",
    connect_args: str = None,
    url: str = None,
):
    if driver != "oracledb":
        raise NotImplementedError("oracledb is currently the only supported driver")
    connect_args_dict = dvt_config_string_to_dict(connect_args) if connect_args else {}
    if thick_mode or not (user or url):
        # thick mode, or credentials in a wallet, which needs thick mode
        oracledb.init_oracle_client(config_dir=connect_args_dict.get("config_dir"))
    backend = OracleBackend()
    if url is not None:
        dsn = url.split("@", 1)[-1]
    elif protocol == "TCP":
        dsn = oracledb.makedsn(host, port, service_name=database)
    else:
        dsn = f"{protocol.lower()}://{host}:{port}/{database}"
    backend.do_connect(user=user, password=password, dsn=dsn, **connect_args_dict)
    return backend
