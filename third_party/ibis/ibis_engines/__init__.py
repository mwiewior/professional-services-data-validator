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
"""DVT's connections to the ibis 12 engines it has no backend of its own for: each takes DVT's
connection fields (text, as `connections add` writes them) and connects ibis's own backend.
An engine whose ibis extra isn't installed fails when connected, naming the extra."""

import importlib
from pathlib import Path


def _int(value, default=None):
    return default if value in (None, "") else int(value)


def _bool(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y")


def _backend(name: str):
    try:
        return getattr(importlib.import_module("ibis"), name)
    except (ImportError, AttributeError) as exc:  # pragma: no cover - the extra's own error
        raise ImportError(
            f"the {name} engine needs DVT's '{name}' extra: "
            f"pip install 'google-pso-data-validator[{name}]'"
        ) from exc


def _connect(name: str, **kwargs):
    """ibis.<name>.connect with the arguments that were given (None ones left to ibis)."""
    return _backend(name).connect(**{k: v for k, v in kwargs.items() if v is not None})


def trino_connect(host="localhost", port=8080, user="dvt", password=None, catalog=None,
                  schema=None, http_scheme=None):
    auth = None
    if password:
        from trino.auth import BasicAuthentication

        auth = BasicAuthentication(user, password)
        http_scheme = http_scheme or "https"
    return _connect("trino", host=host, port=_int(port, 8080), user=user, auth=auth,
                    database=catalog, schema=schema, http_scheme=http_scheme)


def clickhouse_connect(host="localhost", port=None, user="default", password="",
                       database="default", secure=False):
    return _connect("clickhouse", host=host, port=_int(port), user=user, password=password,
                    database=database, secure=_bool(secure))


def duckdb_connect(database=":memory:", read_only=False):
    return _connect("duckdb", database=database, read_only=_bool(read_only))


def sqlite_connect(database=None):
    return _connect("sqlite", database=database)


def athena_connect(s3_staging_dir, region_name=None, schema_name=None, catalog_name=None,
                   work_group=None, profile_name=None):
    return _connect("athena", s3_staging_dir=s3_staging_dir, region_name=region_name,
                    schema_name=schema_name, catalog_name=catalog_name,
                    work_group=work_group, profile_name=profile_name)


def exasol_connect(host="localhost", port=8563, user=None, password=None, schema=None):
    return _connect("exasol", host=host, port=_int(port, 8563), user=user, password=password,
                    schema=schema)


def druid_connect(host="localhost", port=8082, path="/druid/v2/sql", scheme="http",
                  user=None, password=None):
    return _connect("druid", host=host, port=_int(port, 8082), path=path, scheme=scheme,
                    user=user, password=password)


def materialize_connect(host="localhost", port=6875, user="materialize", password=None,
                        database="materialize", schema=None, cluster=None):
    return _connect("materialize", host=host, port=_int(port, 6875), user=user,
                    password=password, database=database, schema=schema, cluster=cluster)


def risingwave_connect(host="localhost", port=4566, user="root", password=None,
                       database="dev", schema=None):
    return _connect("risingwave", host=host, port=_int(port, 4566), user=user,
                    password=password, database=database, schema=schema)


def singlestoredb_connect(host="localhost", port=3306, user="root", password=None,
                          database=None):
    return _connect("singlestoredb", host=host, port=_int(port, 3306), user=user,
                    password=password, database=database)


def _with_files(backend, tables: str):
    """`tables`, "name=path,name=path", each file read as a table of `backend` by its suffix
    (.csv, .parquet, .json)."""
    for item in filter(None, (t.strip() for t in (tables or "").split(","))):
        name, _, path = item.partition("=")
        reader = {".csv": backend.read_csv, ".parquet": backend.read_parquet,
                  ".json": backend.read_json}[Path(path).suffix.lower()]
        reader(path, table_name=name.strip())
    return backend


def datafusion_connect(tables=None):
    return _with_files(_connect("datafusion"), tables)


def polars_connect(tables=None):
    return _with_files(_connect("polars"), tables)


def pyspark_connect(master=None, remote=None, app_name="dvt"):
    """A Spark session: `remote` (Spark Connect, sc://host:15002) or `master` (local[*])."""
    from pyspark.sql import SparkSession

    builder = SparkSession.builder.appName(app_name)
    builder = builder.remote(remote) if remote else builder.master(master or "local[*]")
    return _connect("pyspark", session=builder.getOrCreate())


def flink_connect(mode="batch"):
    """A local Flink table environment, batch or streaming."""
    from pyflink.table import EnvironmentSettings, TableEnvironment

    settings = (EnvironmentSettings.in_streaming_mode() if mode == "streaming"
                else EnvironmentSettings.in_batch_mode())
    return _connect("flink", table_env=TableEnvironment.create(settings))
