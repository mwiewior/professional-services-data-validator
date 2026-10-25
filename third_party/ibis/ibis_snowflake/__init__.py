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
"""DVT's Snowflake backend: ibis 12's (snowflake-connector-python), with DVT's own methods."""

from ibis.backends.snowflake import Backend as SnowflakeBackend


class Backend(SnowflakeBackend):
    def list_primary_key_columns(self, database: str, table: str) -> list:
        """Return a list of primary key column names."""
        # From https://docs.snowflake.com/en/sql-reference/sql/show-primary-keys
        # Column name is 5th field in output.
        with self.con.cursor() as cur:
            cur.execute(f"SHOW PRIMARY KEYS IN {database}.{table}")
            return [_[4] for _ in cur.fetchall()]

    def dvt_list_tables(self, like=None, database=None) -> list:
        return self.list_tables(like=like, database=database)

    def dvt_tuple_in_supported(self) -> bool:
        """Return True if backend client supports native SQL tuple/struct IN expressions."""
        return True
