#!/usr/bin/env python3
"""TDD tests for 3rd round of logic bug review."""

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
# Bug #16: gen_html dates[-1] guarded when all_hist empty
# ================================================================
print("\n" + "=" * 60)
print("Bug #16: gen_html guards dates[-1] against empty all_hist")
print("=" * 60)

v7_path = os.path.join(SCRIPT_DIR, "etf_v7_threefactor.py")
with open(v7_path, "r", encoding="utf-8") as f:
    v7_src = f.read()

# Find the gen_html function and check dates[-1] access
gh_start = v7_src.find("def gen_html(")
gh_end = v7_src.find("\ndef ", gh_start + 1)
gh_func = v7_src[gh_start:gh_end]

# Check if dates[-1] is guarded
if "dates[-1]" in gh_func:
    # Find context around dates[-1]
    d1_pos = gh_func.find("dates[-1]")
    context = gh_func[max(0,d1_pos-80):d1_pos+20]
    guarded = "if dates" in context or "if len(dates)" in context or "dates else" in context
    check("16: gen_html guards dates[-1] against empty list",
          guarded,
          f"dates[-1] unguarded. Context: ...{context}...")
else:
    check("16: gen_html guards dates[-1]", True)


# ================================================================
# Bug #17: analyze_all uses sum(pv)/len(pv) not hardcoded /20
# ================================================================
print("\n" + "=" * 60)
print("Bug #17: analyze_all uses dynamic divisor, not hardcoded /20")
print("=" * 60)

aa_start = v7_src.find("def analyze_all(")
aa_end = v7_src.find("\ndef ", aa_start + 1)
aa_func = v7_src[aa_start:aa_end]

hardcoded_div20 = "sum(pv) / 20" in aa_func
check("17: analyze_all uses sum(pv)/len(pv) not sum(pv)/20",
      not hardcoded_div20,
      "Hardcoded /20 is fragile. Should use /len(pv).")


# ================================================================
# Bug #18: etf_backtest_3y.py divisions guarded against zero price
# ================================================================
print("\n" + "=" * 60)
print("Bug #18: etf_backtest_3y.py price divisions guarded")
print("=" * 60)

bt3y_path = os.path.join(SCRIPT_DIR, "etf_backtest_3y.py")
with open(bt3y_path, "r", encoding="utf-8") as f:
    bt3y_src = f.read()

# Line ~71: idx_chg division
# After fix should have: if idx_prev > 0 else 0
idx_div_guarded = "idx_prev > 0" in bt3y_src or "idx_prev) > 0" in bt3y_src
check("18a: idx_chg division guarded (idx_prev > 0)",
      idx_div_guarded,
      "idx_chg = (idx_c - idx_prev) / idx_prev * 100 has no zero-guard.")

# Line ~102: chg division
chg_guarded = "prev[\"c\"] > 0" in bt3y_src or "prev['c'] > 0" in bt3y_src
check("18b: chg division guarded (prev['c'] > 0)",
      chg_guarded,
      "chg = (c - prev['c']) / prev['c'] * 100 has no zero-guard.")

# Line ~188: buy_hold division
bh_guarded = "records[start_i][\"c\"] > 0" in bt3y_src
check("18c: buy_hold division guarded (records[start_i]['c'] > 0)",
      bh_guarded,
      "INITIAL / records[start_i]['c'] has no zero-guard.")


# ================================================================
# Bug #19: ShareSimulator chg5 division guarded
# ================================================================
print("\n" + "=" * 60)
print("Bug #19: ShareSimulator chg5 division guarded")
print("=" * 60)

uni_path = os.path.join(SCRIPT_DIR, "backtest_unified.py")
with open(uni_path, "r", encoding="utf-8") as f:
    uni_src = f.read()

# Line ~73 in current version: chg5 = (r["c"]-recs[date_idx-5]["c"])/recs[date_idx-5]["c"]*100
# Should be guarded
ss_start = uni_src.find("class ShareSimulator")
ss_end = uni_src.find("\nclass ", ss_start + 1) if uni_src.find("\nclass ", ss_start + 1) > 0 else uni_src.find("\ndef ", ss_start + 1)
ss_func = uni_src[ss_start:ss_end]

# Check if chg5 division line has guard
chg5_guarded = 'recs[date_idx-5][\"c\"]>0' in ss_func or 'recs[date_idx-5][\"c\"] > 0' in ss_func
check("19: ShareSimulator chg5 division guarded",
      chg5_guarded,
      "chg5 division has no zero-guard on recs[date_idx-5]['c'].")


# ================================================================
print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*60}")
if failed > 0:
    print(f"\n  {failed} test(s) FAILED — confirm bugs exist. Fixes needed.")
    sys.exit(1)
else:
    print("  All tests PASSED — bugs are fixed!")
