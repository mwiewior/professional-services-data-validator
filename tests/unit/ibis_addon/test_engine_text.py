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
"""DVT's text of a value on the engines that run in process, executed: a decimal without
trailing zeros (as Oracle writes it), a binary as its lower-case hex, a hash as lower-case hex."""

import decimal
import hashlib

import ibis
import pytest

# Import required in order to register DVT operations.
import third_party.ibis.ibis_addon.operations  # noqa: F401

DECIMALS = ["1234.50", "0.50", "10.00", "-0.01", "7"]
EXPECTED = ["1234.5", "0.5", "10", "-0.01", "7"]


def _engine(name):
    pytest.importorskip(name)
    return getattr(ibis, name).connect()


def _table(con, name):
    import pyarrow as pa

    data = pa.table(
        {
            "d": pa.array([decimal.Decimal(v) for v in DECIMALS], pa.decimal128(10, 2)),
            "b": pa.array([b"\xac\xed\x00\x05"] * 5, pa.binary()),
            "s": pa.array(["Zażółć"] * 5, pa.string()),
        }
    )
    return con.create_table(name, data)


@pytest.mark.parametrize("engine", ["duckdb", "datafusion"])
def test_a_decimals_text_has_no_trailing_zeros(engine):
    con = _engine(engine)
    t = _table(con, "t_dec")
    assert list(con.execute(t.select(x=t.d.cast("string"))).x) == EXPECTED


@pytest.mark.parametrize("engine", ["duckdb", "datafusion"])
def test_a_binarys_text_is_its_lower_case_hex(engine):
    con = _engine(engine)
    t = _table(con, "t_bin")
    assert set(con.execute(t.select(x=t.b.cast("string"))).x) == {"aced0005"}


@pytest.mark.parametrize("engine", ["duckdb", "datafusion"])
def test_a_hash_is_the_lower_case_hex_sha256_of_the_utf8_text(engine):
    con = _engine(engine)
    t = _table(con, "t_hash")
    expected = hashlib.sha256("Zażółć".encode()).hexdigest()
    assert set(con.execute(t.select(x=t.s.hexdigest("sha256"))).x) == {expected}


def test_sqlite_decimal_text_has_no_trailing_zeros():
    con = ibis.sqlite.connect()
    con.raw_sql("CREATE TABLE t (d TEXT)")
    for v in DECIMALS:
        con.raw_sql(f"INSERT INTO t VALUES ('{v}')")
    t = con.table("t").select(d=ibis._.d.cast("decimal(10, 2)"))
    assert list(con.execute(t.select(x=t.d.cast("string"))).x) == EXPECTED


@pytest.mark.parametrize("dialect", ["sqlite", "druid"])
def test_an_engine_without_sha256_refuses_a_hash(dialect):
    t = ibis.table({"s": "string"}, name="t")
    with pytest.raises(Exception, match="(?i)hash|HexDigest"):
        ibis.to_sql(t.select(h=t.s.hexdigest("sha256")), dialect=dialect)
