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
"""DVT's own operations and its per-engine compile rules, on ibis 12's sqlglot compilers.

DVT needs some operations ibis has no form of (a padded CHAR's length, a binary's byte length,
TO_CHAR, a raw SQL filter) and needs others compiled so every engine's text of a value is the same
(a cast to string, a hex hash, epoch seconds), because DVT compares the two sides' values as text
and as hashes of text. ibis 12 compiles an operation `Op` with its compiler's `visit_Op`, so each
rule below is such a method, added to (or wrapping) the compiler of the engine it is for.
"""

import string
from typing import Union

import ibis.expr.datatypes as dt
import ibis.expr.operations as ops
import ibis.expr.rules as rlz
import sqlglot as sg
import sqlglot.expressions as sge
from ibis.backends.sql.compilers import (
    BigQueryCompiler,
    DatabricksCompiler,
    ImpalaCompiler,
    OracleCompiler,
    PySparkCompiler,
)
from ibis.backends.sql.compilers.base import SQLGlotCompiler
from ibis.expr.types import (
    BinaryValue,
    DateValue,
    NumericValue,
    StringValue,
    Table,
    TimestampValue,
    TimeValue,
)

# --- DVT's own operations ---------------------------------------------------------------------


class BinaryLength(ops.Value):
    arg: ops.Value[Union[dt.Binary, dt.String]]
    dtype = dt.int32
    shape = rlz.shape_like("arg")


class PaddedCharLength(ops.Value):
    arg: ops.Value[dt.String]
    dtype = dt.int32
    shape = rlz.shape_like("arg")


class ToChar(ops.Value):
    arg: ops.Value[Union[dt.Decimal, dt.Float64, dt.Date, dt.Time, dt.Timestamp]]
    fmt: ops.Value[dt.String]
    dtype = dt.string
    shape = rlz.shape_like("arg")


class RawSQL(ops.Value):
    """A boolean SQL text taken as it is, for a user's filter (`--filters`)."""

    arg: ops.Value
    sql: str
    dtype = dt.boolean
    shape = rlz.shape_like("arg")


def compile_binary_length(binary_value):
    return BinaryLength(binary_value).to_expr()


def compile_padded_char_length(char_value):
    return PaddedCharLength(char_value).to_expr()


def compile_to_char(numeric_value, fmt):
    return ToChar(numeric_value, fmt=fmt).to_expr()


def compile_raw_sql(table: Table, sql: str):
    return RawSQL(table[table.columns[0]], sql).to_expr()


BinaryValue.byte_length = compile_binary_length
StringValue.padded_char_length = compile_padded_char_length
NumericValue.to_char = compile_to_char
DateValue.to_char = compile_to_char
TimeValue.to_char = compile_to_char
TimestampValue.to_char = compile_to_char


def _method(compiler, name, fn):
    setattr(compiler, f"visit_{name}", fn)


def _wrap(compiler, name, fn):
    """`fn(self, op, original, **kw)`: the engine's rule, falling back to ibis's own `original`."""
    original = getattr(compiler, f"visit_{name}")

    def visit(self, op, **kw):
        return fn(self, op, lambda: original(self, op, **kw), **kw)

    setattr(compiler, f"visit_{name}", visit)


# --- every engine -----------------------------------------------------------------------------


def _visit_raw_sql(self, op, *, arg, sql):
    return sge.Paren(this=sg.parse_one(sql, dialect=self.dialect))


def _visit_binary_length(self, op, *, arg):
    return self.f.length(arg)


def _visit_padded_char_length(self, op, *, arg):
    return self.visit_StringLength(op, arg=arg)


def _visit_to_char(self, op, *, arg, fmt):
    return self.f.to_char(arg, fmt)


_method(SQLGlotCompiler, "RawSQL", _visit_raw_sql)
_method(SQLGlotCompiler, "BinaryLength", _visit_binary_length)
_method(SQLGlotCompiler, "PaddedCharLength", _visit_padded_char_length)
_method(SQLGlotCompiler, "ToChar", _visit_to_char)

# --- Oracle -----------------------------------------------------------------------------------


def _oracle_cast(self, op, original, *, arg, to):
    from_ = op.arg.dtype
    if from_.is_decimal() and to.is_string() and (from_.scale is None or from_.scale > 0):
        # Oracle writes a fraction without its leading zero (0.5 is ".5"); every other engine
        # writes it, so add it back
        return self.if_(
            sg.and_(arg > 0, arg < 1),
            self.f.concat(sge.convert("0"), self.f.to_char(arg)),
            self.if_(
                sg.and_(arg > -1, arg < 0),
                self.f.concat(sge.convert("-0"), self.f.to_char(self.f.abs(arg))),
                self.f.to_char(arg),
            ),
        )
    if from_.is_binary() and to.is_string():
        return self.f.lower(self.f.rawtohex(arg))  # DVT reads a binary as its hex text
    if from_.is_string() and to.is_binary():
        return self.f.hextoraw(arg)
    if from_.is_floating() and to.is_string():
        return self.f.to_char(arg, "TM9")  # never scientific notation
    if from_.is_interval() and to.is_string():
        return self.f.to_char(arg)
    if from_.is_string() and to.is_boolean():
        return self.if_(
            arg.isin(sge.convert("0"), sge.convert("N")),
            sge.convert(0),
            self.if_(arg.isin(sge.convert("1"), sge.convert("Y")), sge.convert(1), NULL),
        )
    if from_.is_boolean() and to.is_string():
        return self.f.lower(self.f.to_char(arg))
    if (from_.is_timestamp() or from_.is_date()) and to.is_date():
        # a DATE everywhere else has no time of day
        return self.cast(self.f.trunc(arg), dt.date)
    return original()


def _oracle_hex_digest(self, op, *, arg, how):
    if how not in ("md5", "sha1", "sha256", "sha512"):
        raise NotImplementedError(f"No available hashing function for {how}")
    # the text's UTF-8 bytes, as every other engine hashes; STANDARD_HASH returns RAW, whose
    # LOWER is its lower-case hex
    return self.f.lower(
        self.f.standard_hash(self.f.convert(arg, sge.convert("UTF8")), sge.convert(how.upper())))


def _oracle_binary_length(self, op, *, arg):
    return sge.Anonymous(this="DBMS_LOB.GETLENGTH", expressions=[arg])


def _oracle_epoch_seconds(self, op, *, arg):
    epoch = self.f.to_date(sge.convert("1970-01-01"), sge.convert("YYYY-MM-DD"))
    days = sge.Paren(this=sge.Sub(this=self.cast(arg, dt.date), expression=epoch))
    return self.cast(sge.Mul(this=days, expression=sge.convert(86400)), dt.Decimal(38, 0))


def _whitespace(self):
    """Every whitespace character, as Python's str.rstrip() strips: a space and CHR()s, since
    not every engine reads escapes in a literal."""
    chars = sge.convert(" ")
    for c in string.whitespace.replace(" ", ""):
        chars = sge.DPipe(this=chars, expression=self.f.chr(ord(c)), safe=True)
    return chars


def _oracle_whitespace_rstrip(self, op, *, arg):
    return self.f.rtrim(arg, _whitespace(self))


def _spark_whitespace_rstrip(self, op, *, arg):
    # Spark's RTRIM takes no character set, its TRIM(TRAILING ...) does
    return sge.Trim(this=arg, expression=_whitespace(self), position="TRAILING")


NULL = sge.Null()
_wrap(OracleCompiler, "Cast", _oracle_cast)
_method(OracleCompiler, "HexDigest", _oracle_hex_digest)
_method(OracleCompiler, "BinaryLength", _oracle_binary_length)
_method(OracleCompiler, "RStrip", _oracle_whitespace_rstrip)
_method(OracleCompiler, "ExtractEpochSeconds", _oracle_epoch_seconds)

# --- BigQuery ---------------------------------------------------------------------------------


def _bigquery_cast(self, op, original, *, arg, to):
    from_ = op.arg.dtype
    if from_.is_binary() and to.is_string():
        return self.f.to_hex(arg)
    if from_.is_string() and to.is_binary():
        return self.f.from_hex(arg)
    return original()


def _bigquery_hex_digest(self, op, *, arg, how):
    if how != "sha256":
        raise NotImplementedError(f"No available hashing function for {how}")
    return self.f.to_hex(self.f.sha256(arg))


def _bigquery_strftime(self, op, *, arg, format_str):
    dtype = op.arg.dtype
    fmt = op.format_str.value
    # GoogleSQL writes a year before 1000 CE with fewer digits unless %E4Y (DVT issue 1181)
    if fmt.startswith("%Y"):
        fmt = fmt.replace("%Y", "%E4Y", 1)
    if dtype.is_date():
        return self.f.format_date(fmt, arg)
    if dtype.is_time():
        return self.f.format_time(fmt, arg)
    if dtype.timezone is None:
        return self.f.format_datetime(fmt, self.f.datetime(arg))
    return self.f.format_timestamp(fmt, self.f.timestamp(arg), dtype.timezone)


def _bigquery_epoch_seconds(self, op, *, arg):
    dtype = op.arg.dtype
    if dtype.is_date() or (dtype.is_timestamp() and dtype.timezone is None):
        return self.f.unix_seconds(self.cast(arg, dt.Timestamp(timezone="UTC")))
    return self.f.unix_seconds(arg)


_wrap(BigQueryCompiler, "Cast", _bigquery_cast)
_method(BigQueryCompiler, "HexDigest", _bigquery_hex_digest)
_method(BigQueryCompiler, "Strftime", _bigquery_strftime)
_method(BigQueryCompiler, "ExtractEpochSeconds", _bigquery_epoch_seconds)

# --- Spark: the emulator's Thrift server (Impala), PySpark and Databricks ---------------------


def _spark_decimal_text(self, arg):
    # Spark writes a decimal's text with its scale (14679.00); Oracle and BigQuery without
    # trailing zeros (14679)
    return self.f.regexp_replace(
        self.f.regexp_replace(self.cast(arg, dt.string), "([.][0-9]*?)0+$", "$1"), "[.]$", "")


def _spark_cast(self, op, original, *, arg, to):
    from_ = op.arg.dtype
    if from_.is_binary() and to.is_string():
        return self.f.lower(self.f.hex(arg))
    if from_.is_string() and to.is_binary():
        return self.f.unhex(arg)
    if from_.is_decimal() and to.is_string():
        return _spark_decimal_text(self, arg)
    if from_.is_boolean() and to.is_string():
        return self.f.lower(self.cast(arg, dt.string))
    return original()


def _spark_hex_digest(self, op, *, arg, how):
    if how == "md5":
        return self.f.md5(arg)
    if how == "sha1":
        return self.f.sha1(arg)
    if how in ("sha256", "sha512"):
        return self.f.sha2(arg, int(how[-3:]))
    raise NotImplementedError(f"No available hashing function for {how}")


def _spark_strftime(self, op, *, arg, format_str):
    # date_format reads a date or timestamp as it is; Spark's ANSI mode refuses the
    # unix_timestamp() round trip of a timestamp's text with fractional seconds
    from sqlglot.dialects.spark import Spark
    from sqlglot.time import format_time

    return self.f.date_format(arg, format_time(op.format_str.value, Spark.INVERSE_TIME_MAPPING,
                                               Spark.INVERSE_TIME_TRIE))


# Databricks too, explicitly: ibis makes each compiler class its own methods for simple operations
for _compiler in (ImpalaCompiler, PySparkCompiler, DatabricksCompiler):
    _wrap(_compiler, "Cast", _spark_cast)
    _method(_compiler, "HexDigest", _spark_hex_digest)
    _method(_compiler, "Strftime", _spark_strftime)
    _method(_compiler, "RandomScalar", lambda self, op, **kw: self.f.rand())
    _method(_compiler, "RStrip", _spark_whitespace_rstrip)
