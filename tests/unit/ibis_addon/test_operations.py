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

from third_party.ibis.ibis_addon import operations


def test_import():
    assert operations is not None


def test_dvt_operations_are_expression_methods():
    import ibis

    t = ibis.table({"s": "string", "b": "binary", "d": "decimal(5, 2)"}, name="t")
    assert t.b.byte_length().type().is_integer()
    assert t.s.padded_char_length().type().is_integer()
    assert t.d.to_char(ibis.literal("FM90.099")).type().is_string()
    assert operations.compile_raw_sql(t, "s = 'x'").type().is_boolean()
