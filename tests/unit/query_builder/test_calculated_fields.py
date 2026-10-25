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
"""Every calculated field DVT builds compiles on ibis 12, on each of Axis's engines."""

import ibis
import pytest

# Import required in order to register DVT operations.
import third_party.ibis.ibis_addon.operations  # noqa: F401
from data_validation.query_builder.query_builder import CalculatedField

TABLE = ibis.table(
    {"s": "string", "b": "binary", "d": "decimal(10, 2)", "ts": "timestamp"},
    name="t",
)

FIELDS = {
    "concat": (CalculatedField.concat, [["s", "s"]], {}),
    "hash": (CalculatedField.hash, ["s"], {}),
    "farm_fingerprint": (
        CalculatedField.hash,
        ["s"],
        {"default_hash_function": "farm_fingerprint"},
    ),
    "to_char": (CalculatedField.to_char, ["d"], {}),
    "ifnull": (CalculatedField.ifnull, ["s"], {}),
    "length": (CalculatedField.length, ["s"], {}),
    "padded_char_length": (CalculatedField.padded_char_length, ["s"], {}),
    "byte_length": (CalculatedField.byte_length, ["b"], {}),
    "rstrip": (CalculatedField.rstrip, ["s"], {}),
    "upper": (CalculatedField.upper, ["s"], {}),
    "epoch_seconds": (CalculatedField.epoch_seconds, ["ts"], {}),
    "cast": (CalculatedField.cast, ["d"], {}),
}


# Fields only one engine's SQL has.
ONLY = {"to_char": "oracle", "farm_fingerprint": "bigquery"}


@pytest.mark.parametrize("dialect", ["oracle", "bigquery", "databricks", "impala"])
@pytest.mark.parametrize("name", sorted(FIELDS))
def test_a_calculated_field_compiles(name, dialect):
    build, fields, extra = FIELDS[name]
    if ONLY.get(name, dialect) != dialect:
        pytest.skip(f"{name} is a {ONLY[name]} field")
    field = build({"field_alias": "x", **extra}, fields)
    sql = str(ibis.to_sql(TABLE.select(field.compile(TABLE)), dialect=dialect))
    assert "x" in sql.lower()


def test_the_hash_is_the_lower_case_hex_sha256():
    field = CalculatedField.hash({"field_alias": "h"}, ["s"])
    sql = str(ibis.to_sql(TABLE.select(field.compile(TABLE)), dialect="bigquery"))
    assert "TO_HEX(SHA256(" in sql.upper()


def test_the_farm_fingerprint_hash_is_bigquerys():
    field = CalculatedField.hash(
        {"field_alias": "h", "default_hash_function": "farm_fingerprint"}, ["s"]
    )
    sql = str(ibis.to_sql(TABLE.select(field.compile(TABLE)), dialect="bigquery"))
    assert "FARM_FINGERPRINT(" in sql.upper()
