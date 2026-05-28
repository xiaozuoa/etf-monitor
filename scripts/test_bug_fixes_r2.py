#!/usr/bin/env python3
"""TDD tests for 10 logic bugs found in 2nd review round."""

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
# Bug #7: base position equity uses "510300_base" key (not "base")
# ================================================================
print("\n" + "=" * 60)
print("Bug #7: base position key matches replace('_base','') lookup")
print("=" * 60)

files_to_check = {
    "backtest_unified.py": ("holding[\"510300_base\"]", "holding[\"base\"]"),
    "etf_backtest_15etf.py": ("holding[\"510300_base\"]", "holding[\"base\"]"),
    "etf_backtest_allmodels.py": ("holding[\"510300_base\"]", "holding[\"base\"]"),
    "etf_optimize_hold.py": ("holding[\"510300_base\"]", "holding[\"base\"]"),
}

for fname, (good_key, bad_key) in files_to_check.items():
    fpath = os.path.join(SCRIPT_DIR, fname)
    with open(fpath, "r", encoding="utf-8") as f:
        src = f.read()
    has_bad = bad_key in src
    has_good = good_key in src
    check(f"7: {fname} base uses '510300_base' not 'base'",
          not has_bad or has_good,
          f"Still uses {bad_key} which won't match replace('_base','')")


# ================================================================
# Bug #8: v4 backtest recomputes ATR daily
# ================================================================
print("\n" + "=" * 60)
print("Bug #8: v4 backtest recomputes ATR during holding period")
print("=" * 60)

v4_path = os.path.join(SCRIPT_DIR, "etf_backtest_v4.py")
with open(v4_path, "r", encoding="utf-8") as f:
    v4_src = f.read()

# Check that ATR is recomputed in the trailing exit path, not just read from pos
trailing_block = v4_src[v4_src.find("if use_trailing:"):v4_src.find("else:", v4_src.find("if use_trailing:"))]
# Should have ATR recomputation inside the trailing block (not just pos.get("atr"))
recomputes_atr = "calc_atr_live" in trailing_block or "trs.append" in trailing_block or "sum(trs)" in trailing_block
check("8: v4 backtest recomputes ATR daily in trailing block",
      recomputes_atr,
      "ATR only fetched from pos dict, never recomputed. Uses stale entry-day ATR.")


# ================================================================
# Bug #9: signal_history stores resonance_min per day
# ================================================================
print("\n" + "=" * 60)
print("Bug #9: signal_history stores resonance_min and uses it")
print("=" * 60)

engine_path = os.path.join(SCRIPT_DIR, "etf_engine.py")
with open(engine_path, "r", encoding="utf-8") as f:
    engine_src = f.read()

# save_signal_history should store resonance_min
save_func = engine_src[engine_src.find("def save_signal_history"):engine_src.find("\ndef ", engine_src.find("def save_signal_history")+1)]
stores_resonance = "resonance_min" in save_func
check("9a: save_signal_history stores resonance_min",
      stores_resonance,
      "Doesn't store resonance_min in signal_history, can't use per-day threshold later.")

# check_consecutive_days should use stored resonance_min per entry
cons_func = engine_src[engine_src.find("def check_consecutive_days"):engine_src.find("\ndef ", engine_src.find("def check_consecutive_days")+1)]
uses_stored = "get(\"resonance_min\"" in cons_func or "[\"resonance_min\"]" in cons_func
check("9b: check_consecutive_days reads per-entry resonance_min",
      uses_stored,
      "Uses global resonance_min for all historical days instead of per-day value.")


# ================================================================
# Bug #10: backtest_unified.py division guarded
# ================================================================
print("\n" + "=" * 60)
print("Bug #10: backtest_unified.py allocation division guarded")
print("=" * 60)

uni_path = os.path.join(SCRIPT_DIR, "backtest_unified.py")
with open(uni_path, "r", encoding="utf-8") as f:
    uni_src = f.read()

unguarded_div = "tb/len(bl)" in uni_src
check("10: backtest_unified.py uses max(len(bl),1) guard",
      not unguarded_div,
      "tb/len(bl) without max(len(bl),1) — ZeroDivisionError if bl empty.")


# ================================================================
# Bug #11: etf_v7_threefactor.py prev_share division guarded
# ================================================================
print("\n" + "=" * 60)
print("Bug #11: etf_v7_threefactor.py prev_share division guarded")
print("=" * 60)

v7_path = os.path.join(SCRIPT_DIR, "etf_v7_threefactor.py")
with open(v7_path, "r", encoding="utf-8") as f:
    v7_src = f.read()

# Line ~366: delta_pct = round(delta_yi / prev_share * 100, 2)
# After fix should have prev_share > 0 guard
gh_func = v7_src[v7_src.find("def get_historical_share"):v7_src.find("\ndef ", v7_src.find("def get_historical_share")+1)]
guarded_prev_share = "prev_share > 0" in gh_func or "prev_share and" in gh_func
check("11: get_historical_share guards against prev_share==0",
      guarded_prev_share,
      "delta_yi / prev_share can divide by zero.")


# ================================================================
# Bug #12: etf_backtest_3y.py imports calc_rs from etf_signals
# ================================================================
print("\n" + "=" * 60)
print("Bug #12: etf_backtest_3y.py imports calc_rs from shared module")
print("=" * 60)

bt3y_path = os.path.join(SCRIPT_DIR, "etf_backtest_3y.py")
with open(bt3y_path, "r", encoding="utf-8") as f:
    bt3y_src = f.read()

imports_calc_rs = "from etf_signals import" in bt3y_src and "calc_rs" in bt3y_src
no_local_calc_rs = "def calc_rs(" not in bt3y_src
check("12: etf_backtest_3y.py imports calc_rs, no local copy",
      imports_calc_rs and no_local_calc_rs,
      "Has local calc_rs definition instead of importing from shared module.")


# ================================================================
# Bug #15: etf_engine.py fetch_shares_confirmation guards prev_shares==0
# ================================================================
print("\n" + "=" * 60)
print("Bug #15: etf_engine.py fetch_shares_confirmation guards prev_shares")
print("=" * 60)

fsc_func = engine_src[engine_src.find("def fetch_shares_confirmation"):engine_src.find("\ndef ", engine_src.find("def fetch_shares_confirmation")+1)]
# Line 171: delta / prev_shares, should have prev_shares > 0 check
guarded_div = "prev_shares > 0" in fsc_func
check("15: fetch_shares_confirmation guards prev_shares > 0 before division",
      guarded_div,
      "delta / prev_shares can divide by zero if prev_shares==0.")


# ================================================================
print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*60}")
if failed > 0:
    print(f"\n  {failed} test(s) FAILED — confirm bugs exist. Fixes needed.")
    sys.exit(1)
else:
    print("  All tests PASSED — bugs are fixed!")
