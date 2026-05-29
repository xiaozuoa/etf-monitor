#!/usr/bin/env python3
"""TDD tests: dynamic weights in ALL CP computation points."""

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

def get_func_body(src, func_name):
    start = src.find(f"def {func_name}(")
    if start == -1:
        return ""
    end = src.find("\ndef ", start + 1)
    if end == -1:
        end = src.find("\nclass ", start + 1)
    if end == -1:
        end = len(src)
    return src[start:end]


print("=" * 60)
print("Dynamic weights coverage audit")
print("=" * 60)

# File 1: etf_signals.py (already has it, baseline check)
sig_path = os.path.join(SCRIPT_DIR, "etf_signals.py")
with open(sig_path, "r", encoding="utf-8") as f:
    sig_src = f.read()
cp_body = get_func_body(sig_src, "compute_cp")
check("0: etf_signals.py compute_cp has dynamic weights (baseline)",
      "idx_chg < 0" in cp_body and "0.20" in cp_body,
      "Baseline already implemented")

# File 2: backtest_unified.py
uni_path = os.path.join(SCRIPT_DIR, "backtest_unified.py")
with open(uni_path, "r", encoding="utf-8") as f:
    uni_src = f.read()
uni_body = get_func_body(uni_src, "compute_cp_unified")
check("1a: backtest_unified.py compute_cp_unified has idx_chg parameter",
      "idx_chg" in uni_body.split("):")[0] if "):" in uni_body else False,
      "compute_cp_unified needs idx_chg parameter for dynamic weights")
check("1b: backtest_unified.py compute_cp_unified has dynamic weight logic",
      "idx_chg < 0" in uni_body and "0.20" in uni_body,
      "compute_cp_unified missing dynamic weight switching")

# File 3: backtest_p0_p1.py
p0p1_path = os.path.join(SCRIPT_DIR, "backtest_p0_p1.py")
with open(p0p1_path, "r", encoding="utf-8") as f:
    p0p1_src = f.read()
cps_start = p0p1_src.find("class CPSystem")
cps_end = p0p1_src.find("\nclass ", cps_start + 1)
if cps_end == -1:
    cps_end = p0p1_src.find("\ndef run_backtest", cps_start + 1)
if cps_end == -1:
    cps_end = len(p0p1_src)
cps_body = p0p1_src[cps_start:cps_end]
check("2: backtest_p0_p1.py CPSystem.compute has dynamic weight logic",
      "idx_chg < 0" in cps_body and "0.20" in cps_body,
      "CPSystem.compute missing dynamic weight switching")

# File 4: etf_backtest_3y.py
bt3_path = os.path.join(SCRIPT_DIR, "etf_backtest_3y.py")
with open(bt3_path, "r", encoding="utf-8") as f:
    bt3_src = f.read()
check("3a: etf_backtest_3y.py no hardcoded 0.50/0.20/0.30 weights",
      "0.50 + d_raw * 0.20 + s_raw * 0.30" not in bt3_src,
      "Still uses hardcoded fixed weights instead of dynamic")
check("3b: etf_backtest_3y.py has dynamic weight logic",
      "idx_chg < 0" in bt3_src and "0.20" in bt3_src,
      "etf_backtest_3y.py missing dynamic weight switching")


print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*60}")
if failed > 0:
    print(f"\n  {failed} test(s) FAILED.")
    sys.exit(1)
else:
    print("  All tests PASSED!")
