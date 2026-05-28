#!/usr/bin/env python3
"""TDD tests for 6th round of logic bug review."""

import os, sys

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
# Bug #26: etf_backtest_3y.py uses align_data (not raw data_dict)
# ================================================================
print("\n" + "=" * 60)
print("Bug #26: etf_backtest_3y uses aligned data")
print("=" * 60)

bt3y_path = os.path.join(SCRIPT_DIR, "etf_backtest_3y.py")
with open(bt3y_path, "r", encoding="utf-8") as f:
    bt3y_src = f.read()

# The backtest function should use aligned data (from align_data), not raw data_dict
# Check if align_data is actually called anywhere
calls_align = "align_data(" in bt3y_src.replace("def align_data(", "")
check("26: etf_backtest_3y calls align_data to align ETF timelines",
      calls_align,
      "align_data defined but never called. Backtest uses unaligned data_dict.")


# ================================================================
# Bug #27: v5/v6 import COMMISSION/SLIPPAGE/INITIAL from etf_signals
# ================================================================
print("\n" + "=" * 60)
print("Bug #27: v5/v6 import constants from etf_signals")
print("=" * 60)

for fname in ["etf_backtest_v5.py", "etf_backtest_v6.py"]:
    fpath = os.path.join(SCRIPT_DIR, fname)
    with open(fpath, "r", encoding="utf-8") as f:
        src = f.read()
    imports_constants = "COMMISSION" in src.split("from etf_signals import")[1].split("\n")[0] if "from etf_signals import" in src else False
    hardcodes = "COMMISSION = 0.00025" in src
    check(f"27: {fname} imports constants from etf_signals, not hardcoded",
          imports_constants and not hardcodes,
          "Hardcoded COMMISSION/SLIPPAGE/INITIAL instead of importing shared values.")


# ================================================================
print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*60}")
if failed > 0:
    print(f"\n  {failed} test(s) FAILED — confirm bugs exist. Fixes needed.")
    sys.exit(1)
else:
    print("  All tests PASSED — bugs are fixed!")
