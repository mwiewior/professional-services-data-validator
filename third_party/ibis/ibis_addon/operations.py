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
    ClickHouseCompiler,
    DatabricksCompiler,
    DataFusionCompiler,
    DruidCompiler,
    DuckDBCompiler,
    ExasolCompiler,
    FlinkCompiler,
    ImpalaCompiler,
    MSSQLCompiler,
    MySQLCompiler,
    OracleCompiler,
    PostgresCompiler,
    PySparkCompiler,
    SnowflakeCompiler,
    SQLiteCompiler,
    TrinoCompiler,
)
from ibis.backends.sql.compilers.base import SQLGlotCompiler
from ibis.backends.sql.compilers.singlestoredb import SingleStoreDBCompiler
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
        # CHR as a plain call: sqlglot's own Chr expression changes shape between releases
        chr_ = sge.Anonymous(this="CHR", expressions=[sge.convert(ord(c))])
        chars = sge.DPipe(this=chars, expression=chr_, safe=True)
    return chars


def _whitespace_rstrip_chars(self, op, *, arg):
    return self.f.rtrim(arg, _whitespace(self))


_oracle_whitespace_rstrip = _whitespace_rstrip_chars


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

# --- Postgres ---------------------------------------------------------------------------------


def _decimal_to_char_format(dtype) -> str:
    precision = dtype.precision or 38
    return "FM" + ("9" * (precision - dtype.scale - 1)) + "0." + ("9" * dtype.scale)


def _postgres_cast(self, op, original, *, arg, to):
    from_ = op.arg.dtype
    if from_.is_decimal() and to.is_string():
        if from_.scale is None:
            # trim_scale() is only available in PostgreSQL 13+ but solves a lot of problems
            # when trying to get consistently formatted numerics.
            return self.cast(self.f.trim_scale(arg), dt.string)
        if from_.scale > 0:
            # Postgres writes the full scale (100.00); to_char without it, and rtrim(".") for
            # a whole number's trailing "."
            return self.f.rtrim(self.f.to_char(arg, _decimal_to_char_format(from_)), ".")
    if from_.is_binary() and to.is_string():
        return self.f.encode(arg, sge.convert("hex"))
    if from_.is_string() and to.is_binary():
        return self.f.decode(arg, sge.convert("hex"))
    return original()


def _postgres_hex_digest(self, op, *, arg, how):
    if how not in ("md5", "sha256", "sha512"):
        raise NotImplementedError(f"No available hashing function for {how}")
    if how == "md5":
        return self.f.md5(arg)
    return self.f.encode(
        self.f[how](self.f.convert_to(arg, sge.convert("UTF8"))), sge.convert("hex"))


def _postgres_epoch_seconds(self, op, *, arg):
    # whole seconds, and as BIGINT for large values, as on the other engines
    return self.cast(
        self.f.extract(sge.Var(this="epoch"), self.f.date_trunc(sge.convert("second"), arg)),
        dt.int64)


def _postgres_padded_char_length(self, op, *, arg):
    # concat '' keeps a bpchar's trailing spaces, which its implicit varchar cast would drop;
    # Postgres's concat reads NULL as '', so a NULL stays NULL first
    return self.f.char_length(
        self.if_(arg.is_(NULL), NULL, self.f.concat(arg, sge.convert(""))))


_wrap(PostgresCompiler, "Cast", _postgres_cast)
_method(PostgresCompiler, "HexDigest", _postgres_hex_digest)
_method(PostgresCompiler, "ExtractEpochSeconds", _postgres_epoch_seconds)
_method(PostgresCompiler, "PaddedCharLength", _postgres_padded_char_length)

# --- MySQL ------------------------------------------------------------------------------------


def _mysql_cast(self, op, original, *, arg, to):
    from_ = op.arg.dtype
    if from_.is_decimal() and from_.scale and from_.scale > 0 and to.is_string():
        # MySQL writes the full scale (100.00); + 0 drops it (https://stackoverflow.com/a/20111398)
        return original() + 0
    if from_.is_binary() and to.is_string():
        return self.f.lower(self.f.hex(arg))
    if from_.is_string() and to.is_binary():
        return self.f.unhex(arg)
    return original()


def _mysql_hex_digest(self, op, *, arg, how):
    if how == "md5":
        return self.f.md5(arg)
    if how in ("sha256", "sha512"):
        return self.f.sha2(arg, sge.convert(how[-3:]))
    raise NotImplementedError(f"No available hashing function for {how}")


def _mysql_strftime(self, op, original, *, arg, format_str):
    if op.arg.dtype.is_timestamp():
        return self.f.date_format(arg, sge.convert("%Y-%m-%d %H:%i:%S"))
    return original()


_wrap(MySQLCompiler, "Cast", _mysql_cast)
_method(MySQLCompiler, "HexDigest", _mysql_hex_digest)
_wrap(MySQLCompiler, "Strftime", _mysql_strftime)

# --- SQL Server -------------------------------------------------------------------------------

_MSSQL_CONVERT_STYLES = {
    "%Y-%m-%d": 23,  # ISO8601
    "%Y-%m-%d %H:%M:%S": 20,  # ODBC canonical
    "%Y-%m-%d %H:%M:%S.%f": 21,  # ODBC canonical (with milliseconds)
}


def _mssql_type(name: str):
    return sge.DataType.build(name, dialect="tsql")


def _mssql_cast(self, op, original, *, arg, to):
    from_ = op.arg.dtype
    if from_.is_floating() and to.is_string():
        return self.f.format(arg, sge.convert("G"))  # never scientific notation
    if from_.is_binary() and to.is_string():
        return self.f.lower(self.f.convert(_mssql_type("VARCHAR(MAX)"), arg, sge.convert(2)))
    if from_.is_string() and to.is_binary():
        return self.f.convert(_mssql_type("VARBINARY(MAX)"), arg, sge.convert(2))
    if from_.is_decimal() and from_.scale and from_.scale > 0 and to.is_string():
        return self.f.format(arg, sge.convert("0." + "#" * from_.scale))
    if from_.is_boolean() and to.is_string():
        return self.if_(arg.eq(0), sge.convert("false"), self.if_(arg.eq(1), sge.convert("true"),
                                                                   NULL))
    return original()


def _mssql_hex_digest(self, op, *, arg, how):
    if how != "sha256":
        raise NotImplementedError(f"No available hashing function for {how}")
    hashed = self.f.hashbytes(sge.convert("SHA2_256"),
                              self.f.convert(_mssql_type("VARCHAR(MAX)"), arg))
    return self.f.lower(self.f.convert(_mssql_type("CHAR(64)"), hashed, sge.convert(2)))


def _mssql_strftime(self, op, *, arg, format_str):
    fmt = op.format_str.value
    if fmt not in _MSSQL_CONVERT_STYLES:
        raise NotImplementedError(f"strftime format {fmt} not supported for SQL Server.")
    if getattr(op.arg.dtype, "timezone", None):
        # comparisons are zone-less: a DATETIME
        arg = self.cast(arg, dt.Timestamp())
    return self.f.convert(_mssql_type("VARCHAR"), arg, sge.convert(_MSSQL_CONVERT_STYLES[fmt]))


def _mssql_epoch_seconds(self, op, *, arg):
    return self.cast(
        self.f.datediff_big(sge.Var(this="s"), sge.convert("1970-01-01 00:00:00"), arg),
        dt.int64)


def _mssql_string_length(self, op, *, arg):
    # characters, not bytes; LEN() ignores trailing spaces, so they become underscores first
    return self.cast(self.f.len(self.f.replace(arg, sge.convert(" "), sge.convert("_"))),
                     dt.int64)


def _mssql_binary_length(self, op, *, arg):
    return self.cast(self.f.datalength(arg), dt.int64)


def _mssql_rstrip(self, op, *, arg):
    return self.f.rtrim(self.cast(arg, dt.String()))


def _mssql_string_join(self, op, original, **kw):
    # SQL Server's CONCAT refuses a single argument (issue-1202)
    if len(op.arg) == 1:
        return kw["arg"][0]
    return original()


def _mssql_sum(self, op, original, **kw):
    # an integer sum as BIGINT, against INT overflow (error 8115)
    if op.arg.dtype.is_integer():
        return self.agg.sum(self.cast(kw["arg"], dt.int64), where=kw.get("where"))
    return original()


def _mssql_mean(self, op, original, **kw):
    # an integer mean as FLOAT, against integer truncation
    if op.arg.dtype.is_integer():
        return self.agg.avg(self.cast(kw["arg"], dt.float64), where=kw.get("where"))
    return original()


_wrap(MSSQLCompiler, "Cast", _mssql_cast)
_method(MSSQLCompiler, "HexDigest", _mssql_hex_digest)
_method(MSSQLCompiler, "Strftime", _mssql_strftime)
_method(MSSQLCompiler, "ExtractEpochSeconds", _mssql_epoch_seconds)
_method(MSSQLCompiler, "StringLength", _mssql_string_length)
_method(MSSQLCompiler, "PaddedCharLength", _mssql_string_length)
_method(MSSQLCompiler, "BinaryLength", _mssql_binary_length)
_method(MSSQLCompiler, "RStrip", _mssql_rstrip)
_method(MSSQLCompiler, "RandomScalar", lambda self, op, **kw: self.f.newid())
_wrap(MSSQLCompiler, "StringJoin", _mssql_string_join)
_wrap(MSSQLCompiler, "Sum", _mssql_sum)
_wrap(MSSQLCompiler, "Mean", _mssql_mean)

# --- Snowflake --------------------------------------------------------------------------------


def _snowflake_cast(self, op, original, *, arg, to):
    from_ = op.arg.dtype
    if from_.is_decimal() and from_.scale and from_.scale > 0 and to.is_string():
        return self.f.rtrim(self.f.to_char(arg, _decimal_to_char_format(from_)), ".")
    if from_.is_binary() and to.is_string():
        return self.f.hex_encode(arg, 0)
    if from_.is_string() and to.is_binary():
        return self.f.hex_decode_binary(arg)
    return original()


def _snowflake_hex_digest(self, op, *, arg, how):
    if how != "sha256":
        raise NotImplementedError(f"No available hashing function for {how}")
    return self.f.sha2(arg)


_wrap(SnowflakeCompiler, "Cast", _snowflake_cast)
_method(SnowflakeCompiler, "HexDigest", _snowflake_hex_digest)
_method(SnowflakeCompiler, "ExtractEpochSeconds",
        lambda self, op, *, arg: self.f.date_part(sge.Var(this="epoch_seconds"), arg))
_method(SnowflakeCompiler, "RStrip", _whitespace_rstrip_chars)

# --- DuckDB: where DVT compares the two sides' results (the combiner) --------------------------


def _duckdb_cast(self, op, original, *, arg, to):
    from_ = op.arg.dtype
    if from_.is_binary() and to.is_string():
        return self.f.lower(self.f.hex(arg))  # DVT reads a binary as its hex text
    if from_.is_timestamp() and from_.timezone is not None and to.is_string():
        # a zoned timestamp's text as Python writes it (+00:00), not DuckDB's +00
        return self.f.regexp_replace(original(), r"([+-][0-9][0-9])$", r"\1:00")
    return original()


_wrap(DuckDBCompiler, "Cast", _duckdb_cast)

# --- ibis 12's other engines ------------------------------------------------------------------

# the strftime tokens DVT's validations write (config_manager._strftime_format)
_STRFTIME_TOKENS = {"%Y": ("YYYY", "yyyy"), "%m": ("MM", "MM"), "%d": ("DD", "dd"),
                    "%H": ("HH24", "HH"), "%M": ("MI", "mm"), "%S": ("SS", "ss")}


def _translated_format(fmt: str, which: int) -> str:
    for token, forms in _STRFTIME_TOKENS.items():
        fmt = fmt.replace(token, forms[which])
    if "%" in fmt:
        raise NotImplementedError(f"No translation of strftime format {fmt!r}")
    return fmt


def _oracle_like_format(fmt: str) -> str:
    return _translated_format(fmt, 0)


def _java_like_format(fmt: str) -> str:
    return _translated_format(fmt, 1)



def _trimmed_decimal_text(self, text):
    """A decimal's text without trailing zeros (1234.50 -> 1234.5, 10.00 -> 10), as Oracle writes
    it, in SQL every engine has (no regex back-references, which differ between engines)."""
    trim = lambda this, chars: sge.Trim(this=this, expression=sge.convert(chars),  # noqa: E731
                                        position="TRAILING")
    return self.if_(sge.Like(this=text, expression=sge.convert("%.%")),
                    trim(trim(text, "0"), "."), text)


def _cast_with(hex_text):
    """A Cast rule: a decimal's text without trailing zeros, a binary's as `hex_text(self, arg)`
    (its lower-case hex; None: ibis's own)."""

    def cast(self, op, original, *, arg, to):
        from_ = op.arg.dtype
        if from_.is_decimal() and to.is_string():
            return _trimmed_decimal_text(self, original())
        if hex_text is not None and from_.is_binary() and to.is_string():
            return hex_text(self, arg)
        return original()

    return cast


def _sha256_only(fn):
    """A HexDigest rule for an engine whose SQL has SHA-256 only."""

    def hex_digest(self, op, *, arg, how):
        if how != "sha256":
            raise NotImplementedError(f"No available hashing function for {how}")
        return fn(self, arg)

    return hex_digest


def _no_sha256(engine):
    def hex_digest(self, op, *, arg, how):
        raise NotImplementedError(f"{engine} has no SHA-256 function: no hash validation")

    return hex_digest


_lower_hex = lambda self, arg: self.f.lower(self.f.hex(arg))  # noqa: E731
_ENGINE_TEXT = {
    # Trino (Athena's compiler inherits it): to_hex is upper case, sha256 takes varbinary
    TrinoCompiler: (lambda self, arg: self.f.lower(self.f.to_hex(arg)),
                    lambda self, arg: self.f.lower(self.f.to_hex(self.f.sha256(
                        self.f.to_utf8(arg))))),
    ClickHouseCompiler: (_lower_hex, lambda self, arg: self.f.lower(self.f.hex(
        self.f.SHA256(arg)))),
    DataFusionCompiler: (lambda self, arg: self.f.encode(arg, "hex"),
                         lambda self, arg: self.f.encode(self.f.sha256(arg), "hex")),
    DuckDBCompiler: (None, None),  # its binary rule is above, its sha256 is lower-case hex
    SQLiteCompiler: (_lower_hex, None),
    FlinkCompiler: (None, lambda self, arg: self.f.sha256(arg)),  # hex text already
    ExasolCompiler: (None, lambda self, arg: self.f.lower(self.f.hash_sha256(arg))),
    DruidCompiler: (None, None),
}
for _compiler, (_hex, _sha256) in _ENGINE_TEXT.items():
    if _compiler is DuckDBCompiler:
        _wrap(_compiler, "Cast", _cast_with(None))  # after the binary rule above
        continue
    _wrap(_compiler, "Cast", _cast_with(_hex))
    if _sha256 is not None:
        _method(_compiler, "HexDigest", _sha256_only(_sha256))
_method(SQLiteCompiler, "HexDigest", _no_sha256("SQLite"))
_method(DruidCompiler, "HexDigest", _no_sha256("Druid"))
_method(ExasolCompiler, "Strftime", lambda self, op, *, arg, format_str: self.f.to_char(
    arg, sge.convert(_oracle_like_format(op.format_str.value))))
_method(DruidCompiler, "Strftime", lambda self, op, *, arg, format_str: self.f.time_format(
    arg, sge.convert(_java_like_format(op.format_str.value))))

# SingleStoreDB is MySQL's SQL, but its compiler marks a hash unsupported on its own class
_wrap(SingleStoreDBCompiler, "Cast", _mysql_cast)
_method(SingleStoreDBCompiler, "HexDigest", _mysql_hex_digest)
