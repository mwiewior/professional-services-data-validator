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
"""DVT's Oracle backend: ibis 12's, with DVT's own reading of Oracle's types (a DATE is a date,
a NUMBER a decimal of its own precision), its session settings and its Oracle-only methods."""

from functools import partial
from typing import Iterable, Optional, Tuple, TypedDict

import ibis.expr.datatypes as dt
import ibis.expr.schema as sch
import oracledb
from ibis.backends.oracle import Backend as OracleBackend
from ibis.backends.oracle.converter import OraclePandasData

ORACLE_SYSTEM_SCHEMAS = {
    "ANONYMOUS",
    "APPQOSSYS",
    "AUDSYS",
    "CTXSYS",
    "DBSFWUSER",
    "DGPDB_INT",
    "DIP",
    "DVF",
    "DVSYS",
    "EXFSYS",
    "FLOWS_FILES",
    "GGSYS",
    "GSMADMIN_INTERNAL",
    "GSMCATUSER",
    "GSMUSER",
    "LBACSYS",
    "MDDATA",
    "MDSYS",
    "MGMT_VIEW",
    "OJVMSYS",
    "OLAPSYS",
    "ORACLE_OCM",
    "ORDDATA",
    "ORDPLUGINS",
    "ORDSYS",
    "OUTLN",
    "PDBADMIN",
    "REMOTE_SCHEDULER_AGENT",
    "SI_INFORMTN_SCHEMA",
    "SPATIAL_CSW_ADMIN_USR",
    "SPATIAL_WFS_ADMIN_USR",
    "SYS",
    "SYS$UMF",
    "SYSBACKUP",
    "SYSDG",
    "SYSKM",
    "SYSMAN",
    "SYSRAC",
    "TSMSYS",
    "WMSYS",
    "XDB",
    "XS$NULL",
}


class _FieldDescription(TypedDict):
    """Type of result of oracledb.Cursor.description."""

    name: Optional[str]
    data_type: Optional[str]
    display_size: Optional[int]
    internal_size: Optional[int]
    precision: Optional[int]
    scale: Optional[int]
    null_ok: Optional[int]


def _get_type(col: _FieldDescription) -> dt.DataType:
    typename = col[1]
    typ = _type_mapping.get(typename)
    if typ is None:
        raise NotImplementedError(f"Oracle type {typename} is not supported")

    if typename == oracledb.DB_TYPE_NUMBER:
        if col[5] == -127:
            # This will occur if type is NUMBER with no precision/scale or if type is FLOAT.
            typ = partial(typ)
        else:
            typ = partial(typ, precision=col[4], scale=col[5])

    return typ(nullable=bool(col[6]))


_type_mapping = {
    oracledb.DB_TYPE_VARCHAR: dt.String,
    oracledb.DB_TYPE_NVARCHAR: dt.String,
    oracledb.DB_TYPE_CHAR: dt.String,
    oracledb.DB_TYPE_NCHAR: dt.String,
    oracledb.DB_TYPE_DATE: dt.Date,
    oracledb.DB_TYPE_TIMESTAMP: dt.Timestamp,
    oracledb.DB_TYPE_TIMESTAMP_TZ: dt.Timestamp(timezone="UTC"),
    oracledb.DB_TYPE_TIMESTAMP_LTZ: dt.Timestamp(timezone="UTC"),
    oracledb.DB_TYPE_RAW: dt.Binary,
    oracledb.DB_TYPE_LONG_RAW: dt.Binary,
    oracledb.DB_TYPE_BFILE: dt.Binary,
    oracledb.DB_TYPE_NUMBER: dt.Decimal,
    oracledb.DB_TYPE_LONG: dt.String,
    oracledb.DB_TYPE_NCLOB: dt.String,
    oracledb.DB_TYPE_CLOB: dt.String,
    oracledb.DB_TYPE_BLOB: dt.Binary,
    oracledb.DB_TYPE_BINARY_FLOAT: dt.Float32,
    oracledb.DB_TYPE_BINARY_DOUBLE: dt.Float64,
    oracledb.DB_TYPE_INTERVAL_DS: partial(dt.Interval, unit="s"),
    oracledb.DB_TYPE_INTERVAL_YM: partial(dt.Interval, unit="s"),
    oracledb.DB_TYPE_BOOLEAN: dt.Boolean,
}


class _DriverNumbers(OraclePandasData):
    """Oracle results with each NUMBER as the driver returns it (an int, or a float when it has a
    fraction or no scale), as ibis 7 left them: DVT's report text ("2.0" for an unconstrained
    NUMBER key) and its comparison are built on those values."""

    @classmethod
    def convert_Decimal(cls, s, dtype, pandas_type):
        return s


def _unquoted(name: str) -> str:
    """An all lower-case Oracle name is an unquoted one, stored upper-case."""
    return name.upper() if name == name.lower() else name


class Backend(OracleBackend):
    def __init__(self, arraysize: int = 500):
        super().__init__()
        self.arraysize = arraysize

    def _post_connect(self) -> None:
        super()._post_connect()
        self.con.module = "DVT"  # identifies the session in Oracle
        with self.con.cursor() as cur:
            cur.execute("ALTER SESSION SET TIME_ZONE='UTC'")
            # Standardise numeric formatting on en_US (issue 1033).
            cur.execute("ALTER SESSION SET NLS_NUMERIC_CHARACTERS='.,'")
        with self.con.cursor() as cur:
            cur.execute("select sys_context('USERENV', 'SERVICE_NAME') from dual")
            self.database_name = cur.fetchall()[0][0]

    def _fetch_from_cursor(self, cursor, schema: sch.Schema):
        import pandas as pd

        df = pd.DataFrame.from_records(cursor, columns=schema.names, coerce_float=True)
        return _DriverNumbers.convert_table(df, schema)

    def _metadata(self, source: str) -> Iterable[Tuple[str, dt.DataType]]:
        """The types of `source` (a table reference or a query) as DVT reads them, from the
        cursor of its first row."""
        with self.con.cursor() as cur:
            cur.arraysize = self.arraysize
            cur.execute(f"SELECT * FROM {source} t0 WHERE ROWNUM <= 1")
            return [(column[0], _get_type(column)) for column in cur.description]

    def _stored_name(self, name: str, database: str) -> str:
        """`name` as Oracle stores it: a table's own spelling when one matches regardless of
        case, else an unquoted (all lower-case) name's upper case, as SQLAlchemy read it on ibis
        7; ibis 12 quotes every identifier, which in Oracle is case-sensitive."""
        tables = self.list_tables(database=database)
        if name in tables:
            return name
        return next((t for t in tables if t.lower() == name.lower()), _unquoted(name))

    def table(self, name: str, /, *, database=None):
        if isinstance(database, str):
            database = _unquoted(database)
        db = self._to_sqlglot_table(database).db or self.current_database
        return super().table(self._stored_name(name, db), database=database)

    def get_schema(self, name: str, *, catalog: Optional[str] = None,
                   database: Optional[str] = None) -> sch.Schema:
        database = database or self.current_database
        table = self._stored_name(name, database)
        return sch.Schema(dict(self._metadata(f'"{database}"."{table}"')))

    def _get_schema_using_query(self, query: str) -> sch.Schema:
        return sch.Schema(dict(self._metadata(f"({query})")))

    def list_primary_key_columns(self, database: str, table: str) -> list:
        """Return a list of primary key column names."""
        list_pk_col_sql = """
            SELECT cc.column_name
            FROM all_cons_columns cc
            INNER JOIN all_constraints c ON (cc.owner = c.owner AND cc.constraint_name = c.constraint_name AND cc.table_name = c.table_name)
            WHERE c.owner = :1
            AND c.table_name = :2
            AND c.constraint_type = 'P'
            ORDER BY cc.position
        """
        with self.con.cursor() as cur:
            cur.execute(list_pk_col_sql, (database.upper(), table.upper()))
            return [_[0] for _ in cur.fetchall()]

    def raw_column_metadata(
        self, database: str = None, table: str = None, query: str = None
    ) -> Iterable[Tuple]:
        """The standard 7 DB API description fields of each column of `database`.`table` or of
        `query`, with Oracle's own type names: DVT tests them for backend specific transforms."""

        def strip_prefix(s: str):
            return s[8:] if s.startswith("DB_TYPE_") else s

        assert (database and table) or query, "We should never receive all args=None"
        if database and table:
            db_tables = self.list_tables(database=database)
            matched_table = next(
                (t for t in db_tables if t.lower() == table.lower()), table.upper()
            )
            source = f'"{database}"."{matched_table}"'
        else:
            source = f"({query})"
        with self.con.cursor() as cur:
            cur.execute(f"SELECT * FROM {source} t0 WHERE ROWNUM <= 1")
            return [
                (column[0], strip_prefix(column[1].name), *column[2:])
                for column in cur.description
            ]

    def is_char_type_padded(self, char_type: Tuple) -> bool:
        """Whether a character type is padded and returns padded values, which DVT may trim."""
        return char_type[0] in ["CHAR", "NCHAR"]

    def list_databases(self, like: Optional[str] = None, **kwargs) -> list[str]:
        """User schemas, without Oracle-maintained system schemas (slow and often not readable)."""
        with self.con.cursor() as cur:
            cur.execute("SELECT username FROM all_users")
            schemas = [row[0] for row in cur.fetchall()]
        return self._filter_with_like(
            [s for s in schemas if s.upper() not in ORACLE_SYSTEM_SCHEMAS], like)

    def dvt_list_tables(self, like=None, database=None):
        return self.list_tables(like=like, database=database)

    def dvt_tuple_in_supported(self) -> bool:
        """Return True if backend client supports native SQL tuple/struct IN expressions."""
        return True
