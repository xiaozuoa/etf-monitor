#!/usr/bin/env python3
"""Tests for 9 logic errors found in code review. Each test should FAIL before fix, PASS after."""

import os, sys, json, io

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
# Test 1: MA20 must exclude today's volume
# ================================================================
print("\n=== Test 1: MA20 excludes today's volume ===")
# Check etf_signals.py:compute_cp
import etf_signals

# Build synthetic records where today has 100x volume vs history
records = []
for i in range(60):
    records.append({"date": f"2026-01-{i+1:02d}", "o": 4.0, "c": 4.0,
                    "h": 4.1, "l": 3.9, "v": 1000.0})
# Today (day_i=59): 100x spike
records[-1]["v"] = 100000.0

# compute_cp uses day_i; verify the MA20 excludes day_i
cp_result = compute_cp_func_called = False
try:
    # Read the source to verify what range is used
    import inspect
    src = inspect.getsource(etf_signals.compute_cp)
    # Check the range excludes day_i
    uses_correct_range = "day_i - 20)" in src or "day_i-20)" in src
    uses_wrong_range = "day_i - 19)" in src or "day_i-19)" in src
    check("1a: etf_signals.py compute_cp MA20 range excludes today",
          uses_correct_range and not uses_wrong_range,
          f"Wrong range found in source")
except Exception as e:
    check("1a: etf_signals.py compute_cp MA20 range", False, str(e))

# Check etf_engine.py:full_analysis MA20
try:
    import importlib
    engine_src = open(os.path.join(SCRIPT_DIR, "etf_engine.py"), "r", encoding="utf-8").read()
    # Check for the bug pattern: data[-20:] includes today
    bug_pattern1 = "data[-20:]"
    # The fix should use data[-21:-1] or similar
    has_bug = bug_pattern1 in engine_src
    # Also check the vols sum doesn't divide by 20 unconditionally when data < 20
    check("1b: etf_engine.py full_analysis MA20 excludes today",
          not has_bug,
          "data[-20:] includes latest/today in MA20")
except Exception as e:
    check("1b: etf_engine.py full_analysis MA20", False, str(e))

# ================================================================
# Test 2: etf_engine.py uses etf_signals shared module
# ================================================================
print("\n=== Test 2: etf_engine.py imports from etf_signals ===")
try:
    engine_src = open(os.path.join(SCRIPT_DIR, "etf_engine.py"), "r", encoding="utf-8").read()
    imports_signals = "from etf_signals import" in engine_src or "import etf_signals" in engine_src
    has_own_calc_rs = "def calc_relative_strength" in engine_src
    # full_analysis keeps per-factor CP calc for HTML display, but formula matches compute_cp
    uses_calc_rs = "calc_rs(" in engine_src
    check("2a: etf_engine.py imports etf_signals", imports_signals,
          "etf_engine.py should import from etf_signals shared module")
    check("2b: etf_engine.py removed duplicate calc_relative_strength",
          not has_own_calc_rs,
          "Should use etf_signals.calc_rs instead of own copy")
    check("2c: etf_engine.py calls calc_rs from shared module",
          uses_calc_rs,
          "Should call calc_rs from etf_signals shared module")
except Exception as e:
    check("2: etf_engine.py imports", False, str(e))

# ================================================================
# Test 3: fetch() data source order consistent
# ================================================================
print("\n=== Test 3: fetch() data source priority consistent ===")
try:
    signals_src = inspect.getsource(etf_signals.fetch)
    v7_path = os.path.join(SCRIPT_DIR, "etf_v7_threefactor.py")
    v7_src = open(v7_path, "r", encoding="utf-8").read()
    import re

    # Find the data key order in etf_signals.fetch
    # Should have "qfqday" first, then "day" as fallback
    signals_qfqday_first = '"qfqday"' in signals_src and signals_src.index('"qfqday"') < signals_src.index('"day"') if '"qfqday"' in signals_src and '"day"' in signals_src else False

    # Find in v7 fetch function
    v7_fetch_start = v7_src.find("def fetch(")
    v7_fetch_end = v7_src.find("\ndef ", v7_fetch_start + 1)
    if v7_fetch_end == -1:
        v7_fetch_end = v7_src.find("\n# ", v7_fetch_start + 1)
    v7_fetch_src = v7_src[v7_fetch_start:v7_fetch_end]

    v7_qfqday_first = '"qfqday"' in v7_fetch_src and '"day"' in v7_fetch_src and v7_fetch_src.index('"qfqday"') < v7_fetch_src.index('"day"')

    consistent = signals_qfqday_first and v7_qfqday_first
    check("3: fetch() data source order consistent (both qfqday first)",
          consistent,
          f"signals qfqday_first={signals_qfqday_first}, v7 qfqday_first={v7_qfqday_first}")
except Exception as e:
    check("3: fetch() order", False, str(e))

# ================================================================
# Test 4: HIGH threshold consistent at 70
# ================================================================
print("\n=== Test 4: HIGH threshold consistent at 70 ===")
try:
    alert_src = open(os.path.join(SCRIPT_DIR, "etf_alert.py"), "r", encoding="utf-8").read()
    # Should not use 60 for high_n counting
    uses_60_as_high = '>= 60' in alert_src
    check("4: etf_alert.py uses CP>=70 not CP>=60 for HIGH",
          not uses_60_as_high,
          "Found >= 60 for HIGH threshold, should be >= 70")
except Exception as e:
    check("4: HIGH threshold", False, str(e))

# ================================================================
# Test 5: check_consecutive_days uses dynamic threshold
# ================================================================
print("\n=== Test 5: check_consecutive_days respects dynamic params ===")
try:
    engine_src = open(os.path.join(SCRIPT_DIR, "etf_engine.py"), "r", encoding="utf-8").read()
    # The function signature should accept resonance_min parameter
    cons_func_start = engine_src.find("def check_consecutive_days(")
    cons_func_end = engine_src.find("\ndef ", cons_func_start + 1)
    cons_func = engine_src[cons_func_start:cons_func_end]
    accepts_threshold = "resonance_min" in cons_func or "threshold" in cons_func
    # The hardcoded ">= 3" should be replaced with parameter
    hardcoded_3 = ">= 3" in cons_func
    check("5: check_consecutive_days accepts dynamic threshold param",
          accepts_threshold and not hardcoded_3,
          f"accepts_threshold={accepts_threshold}, hardcoded_3={hardcoded_3}")
except Exception as e:
    check("5: consecutive days dynamic", False, str(e))

# ================================================================
# Test 6: detect_market_trend returns above_ma in all paths
# ================================================================
print("\n=== Test 6: detect_market_trend returns above_ma in error path ===")
try:
    engine_src = open(os.path.join(SCRIPT_DIR, "etf_engine.py"), "r", encoding="utf-8").read()
    # Find the detect_market_trend function and its early return
    dt_start = engine_src.find("def detect_market_trend(")
    dt_end = engine_src.find("\ndef ", dt_start + 1)
    dt_func = engine_src[dt_start:dt_end]
    # Check that ALL return statements have above_ma
    return_lines = [l for l in dt_func.split("\n") if '"trend"' in l and 'return' in l.replace('"trend"', '') or ('return' in l and 'neutral' in l and 'slope' in l)]
    # More precise: find the early return with insufficient data
    early_return_lines = [l for l in dt_func.split("\n") if "return" in l and "neutral" in l and "slope" in l]
    all_have_above_ma = all('above_ma' in l for l in early_return_lines)
    check("6: detect_market_trend error path returns above_ma",
          all_have_above_ma,
          "Early return missing above_ma key")
except Exception as e:
    check("6: above_ma in error return", False, str(e))

# ================================================================
# Test 7: record_position only marks most recent as exited
# ================================================================
print("\n=== Test 7: record_position doesn't mark ALL positions exited ===")
try:
    alert_src = open(os.path.join(SCRIPT_DIR, "etf_alert.py"), "r", encoding="utf-8").read()
    rp_start = alert_src.find("def record_position(")
    rp_end = alert_src.find("\ndef ", rp_start + 1)
    rp_func = alert_src[rp_start:rp_end]
    # The bug: iterates all positions and marks un-exited as exited
    # After fix: should only mark the LAST un-exited position
    marks_all = 'for p in positions:' in rp_func and 'p["exited"] = True' in rp_func
    check("7: record_position does not mark ALL positions exited",
          not marks_all,
          "Should only mark latest position, not iterate all")
except Exception as e:
    check("7: record_position", False, str(e))

# ================================================================
# Test 8: analyze_all no unused target_date parameter
# ================================================================
print("\n=== Test 8: analyze_all has no unused target_date parameter ===")
try:
    v7_src = open(os.path.join(SCRIPT_DIR, "etf_v7_threefactor.py"), "r", encoding="utf-8").read()
    aa_start = v7_src.find("def analyze_all(")
    aa_end = v7_src.find("\ndef ", aa_start + 1)
    aa_func = v7_src[aa_start:aa_end]
    has_target_date_param = "target_date" in aa_func.split("\n")[0]  # first line = signature
    # Count uses of target_date in function body
    body = "\n".join(aa_func.split("\n")[1:])
    uses_target_date = "target_date" in body
    check("8: analyze_all removed unused target_date parameter",
          not (has_target_date_param and not uses_target_date),
          "target_date parameter declared but never used in function body")
except Exception as e:
    check("8: unused target_date", False, str(e))

# ================================================================
# Test 9: no unused pfx variable in etf_signals.py:fetch
# ================================================================
print("\n=== Test 9: etf_signals.py fetch no dead pfx variable ===")
try:
    signals_fetch_src = inspect.getsource(etf_signals.fetch)
    # After fix: pfx variable eliminated, pfx2 assigned directly in if/else
    lines = signals_fetch_src.split("\n")
    has_standalone_pfx = any(l.strip().startswith('pfx = "sh"') for l in lines)
    check("9: etf_signals.py fetch no dead pfx variable",
          not has_standalone_pfx,
          "Standalone 'pfx = ...' assignment eliminated, logic inlined")
except Exception as e:
    check("9: dead pfx variable", False, str(e))

# ================================================================
# Test 10: backtest_p0_p1.py CPSystem MA20 excludes today
# ================================================================
print("\n=== Test 10: backtest_p0_p1.py CPSystem MA20 excludes today ===")
try:
    p0p1_src = open(os.path.join(SCRIPT_DIR, "backtest_p0_p1.py"), "r", encoding="utf-8").read()
    wrong_range_count = p0p1_src.count("day_i-19,day_i+1") + p0p1_src.count("day_i-19),day_i+1")
    check("10a: CPSystem.compute MA20 excludes today",
          wrong_range_count == 0,
          f"Found {wrong_range_count} instance(s) of wrong MA20 range")
    wrong_range_count2 = p0p1_src.count("di-19,di+1")
    check("10b: _get_share_delta MA20 excludes today",
          wrong_range_count2 == 0,
          f"Found {wrong_range_count2} instance(s) of wrong MA20 range in _get_share_delta")
except Exception as e:
    check("10: CPSystem MA20", False, str(e))

# ================================================================
# Test 11: backtest_p0_p1.py equity calc uses correct ETF price
# ================================================================
print("\n=== Test 11: backtest_p0_p1.py equity calc uses correct ETF price ===")
try:
    # The bug was using ref[day_i]["c"] for all positions
    # After fix, should use data_dict.get(code,...) like the line 199 area
    bug_pattern = 'ref[day_i]["c"] if day_i<len(ref) else pos["shares"]*pos["entry_price"]'
    still_has_ref_bug = bug_pattern in p0p1_src
    check("11: run_backtest equity calc uses per-ETF price (not ref for all)",
          not still_has_ref_bug,
          "Still using ref (510300) price for all positions")
except Exception as e:
    check("11: equity calc", False, str(e))

# ================================================================
# Test 12: etf_v7_threefactor.py prev day lookup correct
# ================================================================
print("\n=== Test 12: etf_v7_threefactor.py prev_idx lookup correct ===")
try:
    v7_src = open(os.path.join(SCRIPT_DIR, "etf_v7_threefactor.py"), "r", encoding="utf-8").read()
    # Find the prev_idx lookup: should use reversed()
    pidx_start = v7_src.find("prev_idx = None")
    pidx_end = v7_src.find("\n", v7_src.find("idx_gain = round", pidx_start))
    pidx_block = v7_src[pidx_start:pidx_end] if pidx_start > 0 else ""
    uses_reversed = "reversed(idx_300)" in pidx_block
    check("12: prev_idx lookup uses reversed() to find correct previous day",
          uses_reversed,
          "Should iterate reversed to find immediately preceding trading day")
except Exception as e:
    check("12: prev_idx lookup", False, str(e))

# ================================================================
print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*60}")
if failed > 0:
    print("Some tests FAILED — these will pass after fixes are applied.")
    sys.exit(1)
else:
    print("All tests PASSED.")
