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


from contextlib import contextmanager
import copy
import logging
from typing import TYPE_CHECKING, Optional
import warnings

import google.oauth2.service_account
from google.cloud import bigquery
from google.api_core import client_options
import ibis

import pandas

from data_validation import client_info, consts, exceptions
from data_validation.secret_manager import SecretManagerBuilder

from third_party.ibis.ibis_bigquery.api import bigquery_connect
from third_party.ibis.ibis_databricks import databricks_connect
from third_party.ibis.ibis_impala.api import impala_connect
from third_party.ibis import ibis_engines

if TYPE_CHECKING:
    import ibis.expr.schema as sch
    import ibis.expr.types as ir


ibis.options.sql.default_limit = None

# Filter Ibis MySQL error when loading client.table()
warnings.filterwarnings(
    "ignore",
    "`BaseBackend.database` is deprecated; use equivalent methods in the backend",
)


# The engines whose ibis backend keeps one DB-API connection that reconnects by itself, which DVT
# reuses across validations (it opens a new client for every validation on the others)
IBIS_ALCHEMY_BACKENDS = [
    "mysql",
    "oracle",
    "postgres",
    "mssql",
    "snowflake",
]


def dvt_tuple_in_supported(client) -> bool:
    """Return True if backend client supports native SQL tuple/struct IN expressions."""
    if hasattr(client, "dvt_tuple_in_supported"):
        return client.dvt_tuple_in_supported()
    else:
        return False


def _raise_missing_client_error(msg):
    def get_client_call(*args, **kwargs):
        raise Exception(msg)

    return get_client_call


# Teradata and Redshift have no ibis 12 backend yet: the fork's issues #426 and #425
teradata_connect = _raise_missing_client_error(
    "Teradata is not supported on ibis 12 yet (getindata/axis#426)"
)
redshift_connect = _raise_missing_client_error(
    "Redshift is not supported on ibis 12 yet (getindata/axis#425)"
)

# Oracle requires oracledb driver
try:
    from third_party.ibis.ibis_oracle.api import oracle_connect
except ImportError:
    oracle_connect = _raise_missing_client_error("pip install oracledb")

try:
    from third_party.ibis.ibis_snowflake.api import snowflake_connect
except ImportError:
    snowflake_connect = _raise_missing_client_error(
        "pip install snowflake-connector-python && pip install snowflake-sqlalchemy"
    )


# MSSQL requires pyodbc package.
try:
    from third_party.ibis.ibis_mssql.api import mssql_connect
except ImportError:
    mssql_connect = _raise_missing_client_error(
        "pip install 'google-pso-data-validator[mssql]' (pyodbc and an ODBC driver)"
    )

try:
    from third_party.ibis.ibis_postgres import postgres_connect
except ImportError:
    postgres_connect = _raise_missing_client_error("pip install 'psycopg[binary]'")

try:
    from third_party.ibis.ibis_mysql import mysql_connect
except ImportError:
    mysql_connect = _raise_missing_client_error(
        "pip install 'google-pso-data-validator[mysql]' (mysqlclient)"
    )


def get_google_bigquery_client(
    project_id: str,
    credentials=None,
    api_endpoint: Optional[str] = None,
    quota_project_id: Optional[str] = None,
):
    info = client_info.get_http_client_info()
    job_config = bigquery.QueryJobConfig(
        connection_properties=[bigquery.ConnectionProperty("time_zone", "UTC")]
    )
    options = None
    if api_endpoint or quota_project_id:
        options = client_options.ClientOptions(
            api_endpoint=api_endpoint,
        )
    return bigquery.Client(
        project=quota_project_id,
        client_info=info,
        credentials=credentials,
        default_query_job_config=job_config,
        client_options=options,
    )


def _get_google_bqstorage_client(
    credentials=None,
    api_endpoint: Optional[str] = None,
    quota_project_id: Optional[str] = None,
    insecure_channel: bool = False,
):
    from google.cloud import bigquery_storage_v1 as bigquery_storage

    if insecure_channel:
        # Talks to a plaintext (no TLS) BigQuery Storage API endpoint - e.g. a local BigQuery
        # emulator, which serves its gRPC Storage API port without TLS at all, so the client's
        # normal default (a secure channel, regardless of anonymous credentials) fails the SSL
        # handshake outright. There is no `client_options`/`credentials` combination that avoids
        # this; only a channel/transport built without TLS does.
        import grpc
        from google.cloud.bigquery_storage_v1.services.big_query_read import transports

        if not api_endpoint:
            raise ValueError("api_endpoint is required when insecure_channel is set")
        channel = grpc.insecure_channel(api_endpoint)
        transport = transports.BigQueryReadGrpcTransport(channel=channel)
        return bigquery_storage.BigQueryReadClient(transport=transport)

    options = None
    if api_endpoint or quota_project_id:
        options = client_options.ClientOptions(
            api_endpoint=api_endpoint,
        )
    return bigquery_storage.BigQueryReadClient(
        credentials=credentials,
        client_options=options,
    )


def get_bigquery_client(
    project_id: str,
    dataset_id: str = "",
    credentials=None,
    api_endpoint: Optional[str] = None,
    storage_api_endpoint: Optional[str] = None,
    storage_api_insecure_channel: bool = False,
    storage_api_disabled: bool = False,
    anonymous_credentials: bool = False,
    client_project_id: Optional[str] = None,  # to be deprecated in the future
    billing_project_id: Optional[str] = None,
):
    if client_project_id:
        logging.warning(
            "client_project_id is deprecated and will be removed in the future, use --billing-project-id instead"
        )
        billing_project_id = client_project_id
    if anonymous_credentials and credentials is None:
        # A local BigQuery emulator needs no Google identity - and a machine running one often
        # has none, so the default (application-default credentials) would fail outright.
        from google.auth.credentials import AnonymousCredentials

        credentials = AnonymousCredentials()
    google_client = get_google_bigquery_client(
        project_id,
        credentials=credentials,
        api_endpoint=api_endpoint,
        # anonymous: name the project outright - left None, the client looks it up through
        # application-default credentials, the very lookup anonymous mode exists to avoid
        quota_project_id=billing_project_id
        or (project_id if anonymous_credentials else None),
    )
    bqstorage_client = None
    if storage_api_endpoint and not storage_api_disabled:
        bqstorage_client = _get_google_bqstorage_client(
            credentials=credentials,
            api_endpoint=storage_api_endpoint,
            quota_project_id=billing_project_id,
            insecure_channel=storage_api_insecure_channel,
        )

    return bigquery_connect(
        project_id=project_id or client_project_id,
        dataset_id=dataset_id,
        credentials=credentials,
        bigquery_client=google_client,
        bqstorage_client=bqstorage_client,
        storage_api_disabled=storage_api_disabled,
    )


def in_memory_duckdb():
    """An in-memory DuckDB, made from its backend class: `ibis.duckdb` and the backend's own
    version check read package metadata, which a sandboxed or faked file system may hide."""
    import duckdb
    from ibis.backends.duckdb import Backend as DuckDBBackend

    class _DuckDB(DuckDBBackend):
        @property
        def version(self) -> str:
            return duckdb.__version__

    client = _DuckDB()
    client.do_connect()
    return client


def get_pandas_client(table_name, file_path, file_type):
    """Return pandas client and env with file loaded into DataFrame

    table_name (str): Table name to use as reference for file data
    file_path (str): The local, s3, or GCS file path to the data
    file_type (str): The file type of the file (csv, json, orc or parquet)
    """
    if file_type == "csv":
        df = pandas.read_csv(file_path)
    elif file_type == "json":
        df = pandas.read_json(file_path)
    elif file_type == "orc":
        df = pandas.read_orc(file_path)
    elif file_type == "parquet":
        df = pandas.read_parquet(file_path)
    else:
        raise ValueError(f"Unknown Pandas File Type: {file_type}")

    # ibis 10 removed its pandas backend: the file's rows go into an in-memory DuckDB
    client = in_memory_duckdb()
    client.create_table(table_name, df)
    return client


def is_sqlalchemy_backend(client):
    try:
        return bool(client.name in IBIS_ALCHEMY_BACKENDS)
    except Exception:
        return False


def is_oracle_client(client):
    try:
        return client.name == "oracle"
    except TypeError:
        # When no Oracle backend has been installed OracleBackend is not a class
        return False


def _split_bigquery_table_location(schema_name, database_name=None):
    if database_name:
        return database_name, schema_name
    if schema_name and "." in schema_name:
        return schema_name.split(".", 1)
    return None, schema_name


def _split_snowflake_table_location(schema_name, database_name=None):
    if database_name:
        return database_name, schema_name
    if schema_name and "." in schema_name:
        return schema_name.split(".", 1)
    return None, schema_name


def get_ibis_table(client, schema_name, table_name, database_name=None):
    """Return Ibis Table for Supplied Client.

    client (IbisClient): Client to use for table
    schema_name (str): Schema name of table object
    table_name (str): Table name of table object
    database_name (str): Database name (generally default is used)
    """
    if client.name == "bigquery":
        database_name, schema_name = _split_bigquery_table_location(
            schema_name, database_name
        )
        return client.table(table_name, database=(database_name, schema_name)
                            if database_name else schema_name)
    elif client.name == "snowflake":
        database_name, schema_name = _split_snowflake_table_location(
            schema_name, database_name
        )
        return client.table(table_name, database=(database_name, schema_name)
                            if database_name else schema_name)
    elif client.name in ["oracle", "postgres", "mssql"]:
        return client.table(table_name, database=(database_name, schema_name)
                            if database_name else schema_name)
    elif client.name in ("duckdb", "sqlite", "polars", "datafusion") and not schema_name:
        return client.table(table_name)
    else:
        return client.table(table_name, database=schema_name)


def get_ibis_query(client, query) -> "ir.Table":
    """Return Ibis Table from query expression for Supplied Client."""
    iq = client.sql(query)
    iq = iq.rename(dict(zip([_.lower() for _ in iq.columns], iq.columns)))
    return iq


def get_ibis_table_schema(
    client, schema_name: str, table_name: str, database_name=None
) -> "sch.Schema":
    """Return Ibis Table Schema for Supplied Client.

    client (IbisClient): Client to use for table
    schema_name (str): Schema name of table object, may not need this since Backend uses database
    table_name (str): Table name of table object
    database_name (str): Database name (generally default is used)
    """
    if client.name == "bigquery":
        database_name, schema_name = _split_bigquery_table_location(
            schema_name, database_name
        )
        return client.get_schema(table_name, catalog=database_name, database=schema_name)
    elif client.name == "snowflake":
        database_name, schema_name = _split_snowflake_table_location(
            schema_name, database_name
        )
        return client.get_schema(table_name, catalog=database_name, database=schema_name)
    else:
        return client.get_schema(table_name, database=schema_name)


def list_primary_key_columns(client, schema_name: str, table_name: str):
    """The primary key of `schema_name`.`table_name`, or None where the backend has no
    lookup of DVT's own (ibis 12's Trino, ClickHouse, ...)."""
    if not hasattr(client, "list_primary_key_columns"):
        return None
    return client.list_primary_key_columns(schema_name, table_name)


def get_ibis_query_schema(client, query_str) -> "sch.Schema":
    # NJ: I'm not happy about calling a private method but don't see how I can avoid it.
    #     Ibis does not expose a public method like it does for get_schema().
    return client._get_schema_using_query(query_str)


def list_databases(client):
    """Return a list of databases in the DB.
    In version 7.1, Ibis adopted a uniform way of referring (see https://ibis-project.org/concepts/backend-table-hierarchy)
    to a collection of tables as a database, irrespective of the terminology used by the specific backend.
    Here we want the collection of tables that may be used for validation, hence the changing
    the function name to list_databases()."""
    if hasattr(client, "list_databases"):
        try:
            return client.list_databases()
        except NotImplementedError:
            raise NotImplementedError(
                "list_databases is not implemented for this client"
            )


def list_tables(client, schema_name, tables_only=True):
    """Return a list of tables in the DB schema."""
    fn = (
        client.dvt_list_tables
        if tables_only and hasattr(client, "dvt_list_tables")
        else client.list_tables
    )
    if client.name in ["snowflake", "duckdb"]:
        return fn()
    return fn(database=schema_name)


def get_all_tables(client, allowed_schemas=None, tables_only=True):
    """Return a list of tuples with database and table names.

    client (IbisClient): Client to use for tables
    allowed_schemas (List[str]): List of schemas to pull.
    """
    table_objs = []
    schemas = list_databases(client)
    for schema_name in schemas:
        if allowed_schemas and schema_name not in allowed_schemas:
            continue
        try:
            tables = list_tables(client, schema_name, tables_only=tables_only)
        except Exception as e:
            logging.warning(f"List Tables Error: {schema_name} -> {e}")
            continue

        for table_name in tables:
            table_objs.append((schema_name, table_name))

    return table_objs


def get_data_client(connection_config):
    """Return DataClient client from given configuration"""
    connection_config = copy.deepcopy(connection_config)
    source_type = connection_config.pop(consts.SOURCE_TYPE)
    secret_manager_type = connection_config.pop(consts.SECRET_MANAGER_TYPE, None)
    secret_manager_project_id = connection_config.pop(
        consts.SECRET_MANAGER_PROJECT_ID, None
    )

    decrypted_connection_config = {}
    if secret_manager_type is not None:
        sm = SecretManagerBuilder().build(secret_manager_type.lower())
        for config_item in connection_config:
            decrypted_connection_config[config_item] = sm.maybe_secret(
                secret_manager_project_id, connection_config[config_item]
            )
    else:
        decrypted_connection_config = connection_config

    # The ibis_bigquery.connect expects a credentials object, not a string.
    if consts.GOOGLE_SERVICE_ACCOUNT_KEY_PATH in decrypted_connection_config:
        key_path = decrypted_connection_config.pop(
            consts.GOOGLE_SERVICE_ACCOUNT_KEY_PATH
        )
        if key_path:
            logging.warning(
                """"Use of Service Account Keys is strongly discouraged. This option is deprecated and may be removed.
                Run DVT with the service account identity by using application-default-credentials with --impersonate-service-account"""
            )
            decrypted_connection_config["credentials"] = (
                google.oauth2.service_account.Credentials.from_service_account_file(
                    key_path
                )
            )

    if source_type not in CLIENT_LOOKUP:
        msg = 'ConfigurationError: Source type "{source_type}" is not supported'.format(
            source_type=source_type
        )
        raise Exception(msg)

    try:
        data_client = CLIENT_LOOKUP[source_type](**decrypted_connection_config)
        data_client._source_type = source_type
    except Exception as e:
        msg = 'Connection Type "{source_type}" could not connect: {error}'.format(
            source_type=source_type, error=str(e)
        )
        raise exceptions.DataClientConnectionFailure(msg)

    return data_client


@contextmanager
def get_data_client_ctx(*args, **kwargs):
    """Provide get_data_client() via a context manager."""
    client = None
    try:
        client = get_data_client(*args, **kwargs)
        yield client
    finally:
        # TODO When we upgrade Ibis beyond 5.x this try/except may become redundant.
        # https://github.com/GoogleCloudPlatform/professional-services-data-validator/issues/1376
        if hasattr(client, "close"):
            try:
                client.close()
            except Exception as exc:
                # No need to reraise, we can silently fail if exiting throws up an issue.
                logging.warning("Exception closing connection: %s", str(exc))


def get_max_column_length(client):
    """Return the max column length supported by client.

    client (IbisClient): Client to use for tables
    """
    if is_oracle_client(client):
        # We can't reliably know which Version class client.version is stored in
        # because it is out of our control. Therefore using string identification
        # of Oracle <= 12.1 to avoid exceptions of this nature:
        #  TypeError: '<' not supported between instances of 'Version' and 'Version'
        if str(client.version)[:2] in ["10", "11"] or str(client.version)[:4] == "12.1":
            return 30
    return 128


def get_max_in_list_size(client, in_list_over_expressions=False):
    if client.name == "snowflake":
        if in_list_over_expressions:
            # This is a workaround for Snowflake limitation:
            #   SQL compilation error: In-list contains more than 50 non-constant values
            # getattr(..., "cast") expression above is looking for lists where the contents are casts and not simple literals.
            return 50
        else:
            return 16000
    elif is_oracle_client(client):
        # This is a workaround for Oracle limitation:
        #   ORA-01795: maximum number of expressions in a list is 1000
        return 1000
    elif client.name == "mssql":
        # Workaround for SQL Server limitation: 2100 maximum parameters in a single query
        return 2000
    else:
        return None


CLIENT_LOOKUP = {
    consts.SOURCE_TYPE_BIGQUERY: get_bigquery_client,
    consts.SOURCE_TYPE_DATABRICKS: databricks_connect,
    consts.SOURCE_TYPE_IMPALA: impala_connect,
    consts.SOURCE_TYPE_MYSQL: mysql_connect,
    consts.SOURCE_TYPE_ORACLE: oracle_connect,
    consts.SOURCE_TYPE_FILESYSTEM: get_pandas_client,
    consts.SOURCE_TYPE_POSTGRES: postgres_connect,
    consts.SOURCE_TYPE_REDSHIFT: redshift_connect,
    consts.SOURCE_TYPE_TERADATA: teradata_connect,
    consts.SOURCE_TYPE_MSSQL: mssql_connect,
    consts.SOURCE_TYPE_SNOWFLAKE: snowflake_connect,
    # ibis 12's other engines; one whose ibis extra isn't installed fails when connected
    consts.SOURCE_TYPE_ATHENA: ibis_engines.athena_connect,
    consts.SOURCE_TYPE_CLICKHOUSE: ibis_engines.clickhouse_connect,
    consts.SOURCE_TYPE_DATAFUSION: ibis_engines.datafusion_connect,
    consts.SOURCE_TYPE_DRUID: ibis_engines.druid_connect,
    consts.SOURCE_TYPE_DUCKDB: ibis_engines.duckdb_connect,
    consts.SOURCE_TYPE_EXASOL: ibis_engines.exasol_connect,
    consts.SOURCE_TYPE_FLINK: ibis_engines.flink_connect,
    consts.SOURCE_TYPE_MATERIALIZE: ibis_engines.materialize_connect,
    consts.SOURCE_TYPE_POLARS: ibis_engines.polars_connect,
    consts.SOURCE_TYPE_PYSPARK: ibis_engines.pyspark_connect,
    consts.SOURCE_TYPE_RISINGWAVE: ibis_engines.risingwave_connect,
    consts.SOURCE_TYPE_SINGLESTOREDB: ibis_engines.singlestoredb_connect,
    consts.SOURCE_TYPE_SQLITE: ibis_engines.sqlite_connect,
    consts.SOURCE_TYPE_TRINO: ibis_engines.trino_connect,
}
