# Copyright(C) 2023 Google Inc.
#
# Licensed under the Apache License, Version 2.0(the "License"); you may not
# use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.See the
# License for the specific language governing permissions and limitations under
# the License.
import logging

import snowflake.connector  # NOQA fail early if the driver is missing

from data_validation.util import dvt_config_string_to_dict
from third_party.ibis.ibis_snowflake import Backend as SnowflakeBackend

logging.getLogger("snowflake.connector").setLevel(logging.WARNING)


def snowflake_connect(
    user: str,
    password: str,
    account: str,
    database: str,
    warehouse: str = None,
    role: str = None,
    connect_args: str = None,
):
    """Snowflake; `database` as "DATABASE" or "DATABASE/SCHEMA", `connect_args` the
    connector's own options (as on ibis 7, whose SQLAlchemy engine passed them on)."""
    client_args = {"user": user, "password": password, "account": account,
                   "database": database}
    if role:
        client_args["role"] = role
    if warehouse:
        client_args["warehouse"] = warehouse
    if connect_args:
        client_args.update(dvt_config_string_to_dict(connect_args))
    backend = SnowflakeBackend()
    backend.do_connect(**client_args)
    return backend
