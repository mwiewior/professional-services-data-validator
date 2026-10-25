# Copyright 2024 Google LLC
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
"""DVT's Databricks backend: ibis 12's, on Databricks' own SQL connector (a SQL warehouse
refuses the HiveServer2 clients DVT's Impala backend uses)."""

from ibis.backends.databricks import Backend as DatabricksBackend


class Backend(DatabricksBackend):
    def list_primary_key_columns(self, database: str, table: str) -> list:
        """Unity Catalog keys are informational only: DVT takes keys from its arguments."""
        return None

    def dvt_list_tables(self, like=None, database=None):
        return self.list_tables(like=like, database=database)

    def dvt_tuple_in_supported(self) -> bool:
        """Return True if backend client supports native SQL tuple/struct IN expressions."""
        return True


def databricks_connect(
    host: str,
    http_path: str,
    token: str = None,
    catalog: str = None,
    schema: str = "default",
):
    """A Databricks SQL warehouse (or cluster) at `host` and `http_path`, authenticated with a
    personal access token (`token`, else `DATABRICKS_TOKEN`)."""
    backend = Backend()
    backend.do_connect(
        server_hostname=host.removeprefix("https://").rstrip("/"),
        http_path=http_path,
        access_token=token,
        catalog=catalog,
        schema=schema,
    )
    return backend
