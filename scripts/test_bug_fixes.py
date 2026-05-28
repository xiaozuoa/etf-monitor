#!/usr/bin/env python3
"""TDD tests for 6 logic bugs found in code review. Run BEFORE fixes to confirm bugs exist."""

import os, sys, json, io, math, inspect, re

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
# Bug #1: detect_market_trend returns neutral due to off-by-one
# ================================================================
print("\n" + "=" * 60)
print("Bug #1: detect_market_trend off-by-one (always returns neutral)")
print("=" * 60)

with open(os.path.join(SCRIPT_DIR, "etf_engine.py"), "r", encoding="utf-8") as f:
    engine_src = f.read()

# Extract detect_market_trend by finding it directly
dt_start = engine_src.find("def detect_market_trend(")
dt_end = engine_src.find("\ndef ", dt_start + 1)
if dt_end == -1:
    dt_end = engine_src.find("\n# ", dt_start + 1)
dt_func = engine_src[dt_start:dt_end] if dt_start >= 0 else ""

fetches_enough = "ma_period + 11" in dt_func
check("1a: detect_market_trend fetches enough data (ma_period+11, not +10)",
      fetches_enough,
      "Still fetches ma_period+10=60, needs 61 data points.")

# Verify the detect_trend guard condition in etf_signals.py
import etf_signals
sig_src = inspect.getsource(etf_signals.detect_trend)
guard_fixed = "day_i < need - 1" in sig_src
check("1b: detect_trend guard uses day_i < need-1 (not day_i < need)",
      guard_fixed,
      "Guard 'day_i < need' off-by-one. With 60 data points day_i=59 < 60 -> always neutral.")


# ================================================================
# Bug #2: etf_v7_threefactor.py IndexError when date_sig empty
# ================================================================
print("\n" + "=" * 60)
print("Bug #2: etf_v7_threefactor.py crash when date_sig empty")
print("=" * 60)

v7_path = os.path.join(SCRIPT_DIR, "etf_v7_threefactor.py")
with open(v7_path, "r", encoding="utf-8") as f:
    v7_src = f.read()

# Check the context around actual_date for a guard
aa_pos = v7_src.find("actual_date =")
context_before = v7_src[max(0, aa_pos-100):aa_pos]
safe_access = "if date_sig" in context_before
check("2: actual_date guarded against empty date_sig",
      safe_access,
      "No guard before list(date_sig.keys())[-1], will crash on empty data.")


# ================================================================
# Bug #3: Backtest files 4-state vs production 2-state
# ================================================================
print("\n" + "=" * 60)
print("Bug #3: Backtest trend config matches production 2-state")
print("=" * 60)

# Check backtest_unified.py
uni_path = os.path.join(SCRIPT_DIR, "backtest_unified.py")
with open(uni_path, "r", encoding="utf-8") as f:
    uni_src = f.read()
uni_cfg_start = uni_src.find("def get_cfg(")
uni_cfg_end = uni_src.find("\ndef ", uni_cfg_start + 1)
uni_cfg = uni_src[uni_cfg_start:uni_cfg_end] if uni_cfg_start >= 0 else ""
has_4state_uni = 'if a:' in uni_cfg and 'else:' in uni_cfg.split('if a:')[1].split('\n')[0] if 'if a:' in uni_cfg else False
check("3a: backtest_unified.py get_cfg uses 2-state",
      not has_4state_uni,
      "Still has neutral-above/below split. Should match production 2-state.")

# Check backtest_p0_p1.py
p0p1_path = os.path.join(SCRIPT_DIR, "backtest_p0_p1.py")
with open(p0p1_path, "r", encoding="utf-8") as f:
    p0p1_src = f.read()
p0p1_cfg_start = p0p1_src.find("def get_cfg(")
p0p1_cfg_end = p0p1_src.find("\ndef ", p0p1_cfg_start + 1)
p0p1_cfg = p0p1_src[p0p1_cfg_start:p0p1_cfg_end] if p0p1_cfg_start >= 0 else ""
has_4state_p0p1 = 'if a:' in p0p1_cfg and 'else:' in p0p1_cfg.split('if a:')[1].split('\n')[0] if 'if a:' in p0p1_cfg else False
check("3b: backtest_p0_p1.py get_cfg uses 2-state",
      not has_4state_p0p1,
      "Still has neutral-above/below split. Should match production 2-state.")


# ================================================================
# Bug #4: Position sizing caps in etf_alert.py
# ================================================================
print("\n" + "=" * 60)
print("Bug #4: Position sizing has caps")
print("=" * 60)

alert_path = os.path.join(SCRIPT_DIR, "etf_alert.py")
with open(alert_path, "r", encoding="utf-8") as f:
    alert_src = f.read()

se_func = alert_src[alert_src.find("def send_email"):alert_src.find("\ndef ", alert_src.find("def send_email")+1)]

# After fix: sig_pct capped at <=70, total_pct capped at <=80
sig_pct_capped = "sig_pct = min(" in se_func
# Check total_pct is realistically capped (not 100)
total_pct_line = [l for l in se_func.split("\n") if "total_pct" in l]
total_capped = any("min(7" in l or "min(8" in l for l in total_pct_line)

check("4a: sig_pct has reasonable cap",
      sig_pct_capped,
      "sig_pct not capped, can reach 80. Too aggressive.")
check("4b: total_pct capped below 100%",
      total_capped,
      "total_pct = min(100, ...) allows full allocation.")


# ================================================================
# Bug #5: etf_engine.py full_analysis uses shared compute_cp
# ================================================================
print("\n" + "=" * 60)
print("Bug #5: full_analysis uses etf_signals.compute_cp")
print("=" * 60)

fa_func = engine_src[engine_src.find("def full_analysis"):engine_src.find("\ndef ", engine_src.find("def full_analysis")+1)]
calls_compute_cp = "compute_cp(" in fa_func
check("5: full_analysis calls compute_cp from shared module",
      calls_compute_cp,
      "full_analysis manually computes CP, duplicating etf_signals.compute_cp logic.")


# ================================================================
# Bug #6: detect_trend default above_ma=False when data insufficient
# ================================================================
print("\n" + "=" * 60)
print("Bug #6: detect_trend error path above_ma=False (conservative)")
print("=" * 60)

# Only check early-return lines (those with 'neutral' to distinguish from normal return)
dt_early_false = [l for l in sig_src.split("\n")
                  if "above_ma" in l and "return" in l and "neutral" in l]
all_conservative = all("False" in l for l in dt_early_false) if dt_early_false else False
check("6: detect_trend early return has above_ma=False (not True)",
      all_conservative,
      "Default above_ma=True is optimistic. Should be False when data insufficient.")


# ================================================================
print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*60}")
if failed > 0:
    print(f"\n  {failed} test(s) FAILED — these confirm bugs exist. Fixes needed.")
    sys.exit(1)
else:
    print("  All tests PASSED — bugs are fixed!")
