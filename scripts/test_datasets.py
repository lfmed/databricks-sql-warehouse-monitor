"""Executa cada dataset com valores de teste e mostra estado, tempo e amostra.
Uso: python3 scripts/test_datasets.py <profile> <sql_warehouse_exec> "<nome | id>" <dmin> <dmax> [ds ...]
"""
import json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(__file__))
from datasets import DATASETS, for_test

profile, exec_wh, wh, dmin, dmax = sys.argv[1:6]
names = sys.argv[6:] or list(DATASETS)
sqls = [for_test(DATASETS[n], wh, dmin, dmax) for n in names]
env = dict(os.environ, DATABRICKS_WAREHOUSE_ID=exec_wh)
out = subprocess.run(["databricks", "experimental", "aitools", "tools", "query",
                      "--profile", profile, "--output", "json", *sqls],
                     capture_output=True, text=True, env=env)
try:
    res = json.loads(out.stdout)
except Exception:
    print(out.stdout[-3000:], out.stderr[-3000:]); sys.exit(1)
for n, r in zip(names, res):
    rows = r.get("rows") or []
    print(f"== {n}: {r['state']} {r.get('elapsed_ms')}ms rows={len(rows)} err={r.get('error')}")
    print("   cols:", r.get("columns"))
    for row in rows[:4]:
        print("  ", [str(v)[:60] if v is not None else None for v in row])
