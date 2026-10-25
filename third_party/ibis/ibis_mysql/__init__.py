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
"""DVT's MySQL backend: ibis 12's (mysqlclient), with DVT's own MySQL methods."""

from ibis.backends.mysql import Backend as MySQLBackend


class Backend(MySQLBackend):
    def list_primary_key_columns(self, database: str, table: str) -> list:
        """Return a list of primary key column names."""
        list_pk_col_sql = """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND COLUMN_KEY = 'PRI'
            ORDER BY ORDINAL_POSITION
            """
        with self.con.cursor() as cur:
            cur.execute(list_pk_col_sql, (database, table))
            return [_[0] for _ in cur.fetchall()]

    def dvt_list_tables(self, like=None, database=None) -> list:
        return self.list_tables(like=like, database=database)

    def dvt_tuple_in_supported(self) -> bool:
        """Return True if backend client supports native SQL tuple/struct IN expressions."""
        return True


def mysql_connect(host="localhost", port=3306, user=None, password=None, database=None):
    backend = Backend()
    backend.do_connect(host=host, port=int(port), user=user, password=password,
                       database=database)
    return backend
