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
"""DVT's BigQuery backend: ibis 12's, plus REST-only reads for a local BigQuery emulator."""

from ibis.backends.bigquery import Backend as BigQueryBackend


class _RestOnly:
    """A query's result read through the REST API only: a local emulator's Storage API can't
    serve anonymous query-result tables, and Google's client creates a Storage client by itself
    unless told not to (`create_bqstorage_client=False`)."""

    def __init__(self, rows):
        self._rows = rows

    def __getattr__(self, name):
        return getattr(self._rows, name)

    def to_arrow(self, *args, **kwargs):
        return self._rows.to_arrow(
            *args, **{**kwargs, "bqstorage_client": None, "create_bqstorage_client": False}
        )

    def to_arrow_iterable(self, *args, **kwargs):
        return self._rows.to_arrow_iterable(*args, **{**kwargs, "bqstorage_client": None})

    def to_dataframe(self, *args, **kwargs):
        return self._rows.to_dataframe(
            *args, **{**kwargs, "bqstorage_client": None, "create_bqstorage_client": False}
        )


class Backend(BigQueryBackend):
    def do_connect(self, *args, storage_api_disabled: bool = False, **kwargs):
        super().do_connect(*args, **kwargs)
        self.storage_api_disabled = storage_api_disabled
        if storage_api_disabled:
            self.storage_client = None

    def _to_query(self, *args, **kwargs):
        rows = super()._to_query(*args, **kwargs)
        return _RestOnly(rows) if self.storage_api_disabled else rows

    def list_primary_key_columns(self, database: str, table: str) -> list:
        """Return a list of primary key column names."""
        # TODO: Related to issue-1253, it's not clear if this is possible, we should revisit if it becomes a requirement.
        return None

    def dvt_list_tables(self, like=None, database=None):
        return self.list_tables(like=like, database=database)

    def dvt_tuple_in_supported(self) -> bool:
        """Return True if backend client supports native SQL tuple/struct IN expressions."""
        return True
