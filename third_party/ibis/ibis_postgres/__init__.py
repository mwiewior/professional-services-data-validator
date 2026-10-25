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
"""DVT's PostgreSQL backend: ibis 12's (psycopg), with DVT's own PostgreSQL methods."""

from typing import Iterable, Tuple

from ibis.backends.postgres import Backend as PostgresBackend


class Backend(PostgresBackend):
    def list_primary_key_columns(self, database: str, table: str) -> list:
        """Return a list of primary key column names."""
        # From https://wiki.postgresql.org/wiki/Retrieve_primary_key_columns
        list_pk_col_sql = """
            SELECT a.attname
            FROM   pg_index i
            JOIN   pg_attribute a ON a.attrelid = i.indrelid
                                 AND a.attnum = ANY(i.indkey)
            WHERE  i.indrelid = CAST(%s AS regclass)
            AND    i.indisprimary
            """
        with self.con.cursor() as cur:
            cur.execute(list_pk_col_sql, (f"{database}.{table}",))
            return [_[0] for _ in cur.fetchall()]

    def raw_column_metadata(
        self, database: str = None, table: str = None, query: str = None
    ) -> Iterable[Tuple]:
        """The standard 7 DB API description fields of each column of `database`.`table` or of
        `query`, with PostgreSQL's own type names (format_type): DVT tests them for backend
        specific transforms."""
        assert (database and table) or query, "We should never receive all args=None"
        source = f'"{database}"."{table}"' if database and table else f"({query})"
        with self.con.cursor() as cur:
            cur.execute(f"SELECT * FROM {source} t0 LIMIT 0")
            columns = list(cur.description)
            cur.execute(
                "SELECT format_type(t, NULL) FROM unnest(%s::oid[]) WITH ORDINALITY AS u(t, n)"
                " ORDER BY n",
                ([c.type_code for c in columns],),
            )
            type_names = [_[0] for _ in cur.fetchall()]
        return [
            (c.name, type_name, c.display_size, c.internal_size, c.precision, c.scale,
             c.null_ok)
            for c, type_name in zip(columns, type_names)
        ]

    def is_char_type_padded(self, char_type: Tuple) -> bool:
        """Whether a character type is padded and returns padded values, which DVT may trim."""
        return char_type[0] == "character"

    def dvt_list_tables(self, like=None, database=None) -> list:
        return self.list_tables(like=like, database=database)

    def dvt_tuple_in_supported(self) -> bool:
        """Return True if backend client supports native SQL tuple/struct IN expressions."""
        return True


def postgres_connect(host="localhost", port=5432, user=None, password=None, database=None,
                     schema=None):
    backend = Backend()
    backend.do_connect(host=host, port=int(port), user=user, password=password,
                       database=database, schema=schema)
    return backend
