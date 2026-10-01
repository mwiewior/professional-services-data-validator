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

from unittest import mock

from google.auth import credentials

from data_validation import clients, consts


@mock.patch("google.auth.default")
def test_bigquery_custom_endpoints(mock_default):
    mock_credentials = mock.create_autospec(credentials.Credentials)
    mock_default.return_value = (mock_credentials, "test-project")

    api_endpoint = "https://bigquery-custom.googleapis.com"
    storage_api_endpoint = "https://bigquerystorage-custom.googleapis.com"

    conn_config = {
        consts.SOURCE_TYPE: consts.SOURCE_TYPE_BIGQUERY,
        consts.PROJECT_ID: "test-project",
        consts.API_ENDPOINT: api_endpoint,
        consts.STORAGE_API_ENDPOINT: storage_api_endpoint,
    }

    ibis_client = clients.get_data_client(conn_config)

    assert ibis_client.client._connection.API_BASE_URL == api_endpoint
    assert ibis_client.storage_client.api_endpoint == storage_api_endpoint


def test_bigquery_emulator_connection_needs_no_google_credentials_or_storage_api():
    """--anonymous-credentials + --storage-api-disabled: a local BigQuery emulator reached over
    REST needs no Google identity, and its Storage API cannot serve query-result tables - so no
    application-default credentials lookup and no Storage API client at all, even with a
    storage endpoint configured."""
    from google.auth.credentials import AnonymousCredentials

    conn_config = {
        consts.SOURCE_TYPE: consts.SOURCE_TYPE_BIGQUERY,
        consts.PROJECT_ID: "axis-local",
        consts.API_ENDPOINT: "http://localhost:9050",
        consts.STORAGE_API_ENDPOINT: "localhost:9060",
        consts.STORAGE_API_DISABLED: True,
        consts.ANONYMOUS_CREDENTIALS: True,
    }

    with mock.patch("google.auth.default") as mock_default:
        ibis_client = clients.get_data_client(conn_config)

    mock_default.assert_not_called()
    assert isinstance(ibis_client.client._credentials, AnonymousCredentials)
    assert ibis_client.client._connection.API_BASE_URL == "http://localhost:9050"
    assert ibis_client.storage_client is None
    assert ibis_client.storage_api_disabled is True


def test_storage_api_disabled_reads_query_results_through_rest_only():
    """With the Storage API disabled, `to_arrow` must never create a Storage API client."""
    from third_party.ibis.ibis_bigquery import Backend

    backend = Backend()
    backend.storage_client = None
    backend.storage_api_disabled = True
    backend.billing_project = "axis-local"
    cursor = mock.Mock()
    query_result = cursor.query.result.return_value
    query_result._project = "axis-local"

    backend._cursor_to_arrow(cursor)

    _args, kwargs = query_result.to_arrow.call_args
    assert kwargs["create_bqstorage_client"] is False
    assert kwargs["bqstorage_client"] is None
