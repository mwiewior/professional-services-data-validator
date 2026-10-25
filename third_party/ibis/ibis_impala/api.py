# Copyright 2020 Google LLC
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
"""DVT's Impala backend: ibis 12's, reached over HiveServer2 (Impala, Hive or a Spark Thrift
server), with DVT's own reading of the server's type names (Spark's `timestamp_ntz` included)."""

import re
from functools import lru_cache
from typing import Literal

import ibis
import ibis.expr.datatypes as dt
import ibis.expr.schema as sch
from ibis.backends.impala import Backend as ImpalaBackend

_SIMPLE_TYPES = {
    "boolean": dt.boolean, "tinyint": dt.int8, "smallint": dt.int16, "int": dt.int32,
    "integer": dt.int32, "bigint": dt.int64, "float": dt.float32, "double": dt.float64,
    "real": dt.float64, "string": dt.string, "date": dt.date, "timestamp": dt.timestamp,
    # Spark 3.4+'s zone-less timestamp (Databricks, the Spark emulator)
    "timestamp_ntz": dt.timestamp, "binary": dt.binary,
}


def parse_type(t: str) -> dt.DataType:
    """The ibis type of a HiveServer2 type name (DESCRIBE's, or a cursor description's)."""
    t = t.lower().strip()
    if t in _SIMPLE_TYPES:
        return _SIMPLE_TYPES[t]
    if t.startswith(("varchar", "char")):
        return dt.string
    if t.startswith("decimal"):
        match = re.match(r"decimal\((\d+),\s*(\d+)\)", t)
        return dt.Decimal(int(match[1]), int(match[2])) if match else dt.Decimal()
    if t.startswith(("struct", "array", "map")):
        # Supports parsing through structs/arrays in schema in #444
        t = re.sub(r":(bigint)\b", ":int64", t)
        t = re.sub(r":(tinyint)\b", ":int8", t)
        t = re.sub(r":(smallint)\b", ":int16", t)
        t = re.sub(r":(int)\b", ":int32", t)
        t = re.sub(r":(varchar|char)(\(\d+\))?", ":string", t)
        return dt.dtype(t)
    raise NotImplementedError(f"Unsupported HiveServer2 type: {t}")


def update_query_with_limit(query):
    limit_pattern = re.compile(r"LIMIT\s+\d+(\s+OFFSET\s+\d+)?\s*;?\s*$", re.IGNORECASE)
    last_limit_match = limit_pattern.search(query)
    if last_limit_match:
        return query[: last_limit_match.start()] + "LIMIT 1" + query[last_limit_match.end():]
    return query + " LIMIT 1"


class Backend(ImpalaBackend):
    def get_schema(self, table_name, *, catalog=None, database=None) -> sch.Schema:
        name = f"`{database}`.`{table_name}`" if database else f"`{table_name}`"
        with self.con.cursor() as cur:
            cur.execute(f"DESCRIBE {name}")
            rows = cur.fetchall()
        pairs = []
        for row in rows:
            # Add check for empty row for Hive partitioned tables in #375
            if row[0] == "" or row[0].startswith("#"):
                break
            pairs.append((row[0], parse_type(row[1])))
        return sch.Schema(dict(pairs))

    @lru_cache(maxsize=2)
    def _get_schema_using_query(self, query):
        # Removing LIMIT 0 around query since it returns no results in Hive
        with self.con.cursor() as cur:
            cur.execute(update_query_with_limit(query))
            cur.fetchall()
            fields = {}
            for name, type_code, _display, _internal, precision, scale, _null_ok in cur.description:
                name = name.split(".")[-1]
                type_name = type_code.lower()
                if type_name == "decimal" and precision is not None:
                    fields[name] = dt.Decimal(precision, scale)
                else:
                    fields[name] = parse_type(type_name)
        return sch.Schema(fields)

    def list_primary_key_columns(self, database: str, table: str) -> list:
        """No primary keys in Hadoop."""
        return None

    def dvt_list_tables(self, like=None, database=None):
        """dvt_list_tables is a pass through on Hadoop due to "show tables" behaviour."""
        return self.list_tables(like=like, database=database)


def impala_connect(
    host: str = "localhost",
    port: int = 10000,
    database: str = "default",
    timeout: int = 45,
    use_ssl: bool = False,
    ca_cert: str = None,
    user: str = None,
    password: str = None,
    auth_mechanism: Literal["NOSASL", "PLAIN", "GSSAPI", "LDAP"] = "PLAIN",
    kerberos_service_name: str = "impala",
    pool_size: int = 8,
    hdfs_client=None,
    use_http_transport: bool = False,
    http_path: str = "",
):
    backend = Backend()
    backend.do_connect(
        host=host, port=int(port), database=database, timeout=timeout, use_ssl=use_ssl,
        ca_cert=ca_cert, user=user, password=password, auth_mechanism=auth_mechanism,
        kerberos_service_name=kerberos_service_name, use_http_transport=use_http_transport,
        http_path=http_path,
    )
    try:
        backend.raw_sql("set hive.resultset.use.unique.column.names=false")
    except Exception:
        pass
    return backend
