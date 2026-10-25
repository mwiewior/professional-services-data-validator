"""Debug aid (not a test): each side's row text for Oracle against an engine."""
import json, os, subprocess, sys
from tests.system.ibis12 import conftest
from tests.system.ibis12.engines import ENGINES, ORACLE

home = "/tmp/dvt-conn"
os.makedirs(home, exist_ok=True)
os.environ["PSO_DV_CONN_HOME"] = home
conftest._bootstrap_mssql()
for e in (ORACLE, *ENGINES.values()):
    conftest.dvt("connections", "add", "-c", e.name, *e.connection)
for target in sys.argv[1:]:
    t = ENGINES[target]
    out = conftest.dvt_json("validate", "row", "-sc", "oracle", "-tc", target, "-tbls",
                            f"DVT.DVT_CORE={t.schema}.dvt_core", "--primary-keys", "id",
                            "--concat", "*")
    print("=====", target)
    for r in sorted(out, key=lambda r: r["group_by_columns"]):
        if r["validation_status"] != "success":
            print(r["group_by_columns"], "\n  ora:", r["source_agg_value"], "\n  tgt:", r["target_agg_value"])
