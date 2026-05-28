#!/usr/bin/env python3
"""TDD tests for 7th round - cross-file consistency fixes."""

import os, sys, re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}  -- {detail}")


# ================================================================
# Bug #28: etf_engine WORKSPACE supports ETF_WORKSPACE env var
# ================================================================
print("\n" + "=" * 60)
print("Bug #28: etf_engine WORKSPACE supports ETF_WORKSPACE env var")
print("=" * 60)

engine_path = os.path.join(SCRIPT_DIR, "etf_engine.py")
with open(engine_path, "r", encoding="utf-8") as f:
    engine_src = f.read()

# etf_engine.py WORKSPACE should support ETF_WORKSPACE env var like v7 does
ws_line = [l for l in engine_src.split("\n") if "WORKSPACE = " in l and "os.path" in l]
has_env = any("ETF_WORKSPACE" in l or "environ" in l for l in ws_line)
check("28: etf_engine.py WORKSPACE supports ETF_WORKSPACE env var",
      has_env,
      f"WORKSPACE hardcoded without env var support. v7/data_store support it but engine doesn't. "
      f"Setting ETF_WORKSPACE splits files across dirs.")


# ================================================================
# Bug #29: etf_alert.py backup imports match intended engine
# ================================================================
print("\n" + "=" * 60)
print("Bug #29: alert backups have documented import mismatch")
print("=" * 60)

# etf_alert_v3_backup.py and v4a_backup import from etf_engine (15-ETF)
# but were originally paired with 7-ETF engines. Document this.
alert_v3_path = os.path.join(SCRIPT_DIR, "etf_alert_v3_backup.py")
with open(alert_v3_path, "r", encoding="utf-8") as f:
    v3_src = f.read()
# Check if there's a comment noting the pool size mismatch
has_doc_v3 = "15-ETF" in v3_src or "7-ETF" in v3_src or "ETF池" in v3_src
check("29a: etf_alert_v3_backup.py documents ETFS import source",
      has_doc_v3,
      "Imports from etf_engine (15-ETF pool) but originally paired with 7-ETF engine. Undocumented drift.")

alert_v4a_path = os.path.join(SCRIPT_DIR, "etf_alert_v4a_backup.py")
with open(alert_v4a_path, "r", encoding="utf-8") as f:
    v4a_src = f.read()
has_doc_v4a = "15-ETF" in v4a_src or "7-ETF" in v4a_src or "ETF池" in v4a_src
check("29b: etf_alert_v4a_backup.py documents ETFS import source",
      has_doc_v4a,
      "Imports from etf_engine (15-ETF pool) but originally paired with 7-ETF engine. Undocumented drift.")


# ================================================================
print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*60}")
if failed > 0:
    print(f"\n  {failed} test(s) FAILED — confirm bugs exist. Fixes needed.")
    sys.exit(1)
else:
    print("  All tests PASSED — bugs are fixed!")
