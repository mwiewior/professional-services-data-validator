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
"""DVT's SQL Server backend: ibis 12's (pyodbc), with DVT's own SQL Server methods."""

from contextlib import closing
from typing import Iterable, Tuple

from ibis.backends.mssql import Backend as MSSQLBackend

DEFAULT_DRIVER_NAME = "ODBC Driver 17 for SQL Server"


class Backend(MSSQLBackend):
    def _rows(self, sql: str, *params) -> list:
        with closing(self.con.cursor()) as cur:
            cur.execute(sql, *params)
            return cur.fetchall()

    def list_primary_key_columns(self, database: str, table: str) -> list:
        """Return a list of primary key column names."""
        list_pk_col_sql = """
            SELECT COL_NAME(ic.object_id, ic.column_id) AS column_name
            FROM sys.tables t
            INNER JOIN sys.indexes i ON (t.object_id = i.object_id)
            INNER JOIN sys.index_columns ic ON (i.object_id = ic.object_id AND i.index_id  = ic.index_id)
            INNER JOIN sys.schemas s ON (t.schema_id = s.schema_id)
            WHERE  s.name = ?
            AND    t.name = ?
            AND    i.is_primary_key = 1
            ORDER BY ic.column_id"""
        return [_[0] for _ in self._rows(list_pk_col_sql, database, table)]

    def raw_column_metadata(
        self, database: str = None, table: str = None, query: str = None
    ) -> Iterable[Tuple]:
        """The standard 7 DB API description fields of each column of `database`.`table` or of
        `query`, with SQL Server's own type names (sp_describe_first_result_set): DVT tests them
        for backend specific transforms."""
        assert (database and table) or query, "Must provide either database/table or query"
        sql = f"SELECT TOP 1 * FROM [{database}].[{table}]" if database and table else query
        with closing(self.con.cursor()) as cur:
            cur.execute("EXEC sp_describe_first_result_set @tsql = ?", sql)
            names = [d[0] for d in cur.description]
            for row in cur.fetchall():
                column = dict(zip(names, row))
                system_type = column["system_type_name"]
                yield (
                    column["name"],
                    system_type.split("(")[0].strip().lower() if system_type else None,
                    column["max_length"],
                    column["max_length"],
                    column["precision"],
                    column["scale"],
                    column["is_nullable"],
                )

    def is_char_type_padded(self, char_type: Tuple) -> bool:
        """Whether a character type is padded and returns padded values, which DVT may trim."""
        return char_type[0] in ["char", "nchar"]

    def dvt_list_tables(self, like=None, database=None) -> list:
        return self.list_tables(like=like, database=database)

    def dvt_tuple_in_supported(self) -> bool:
        """Return True if backend client supports native SQL tuple/struct IN expressions."""
        return False
