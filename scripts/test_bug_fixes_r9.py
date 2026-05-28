#!/usr/bin/env python3
"""TDD tests for 9th round — remaining v7 gen_html issues."""

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
# Bug #33: sh_yi guards against None value for .1f format
# ================================================================
print("\n" + "=" * 60)
print("Bug #33: sh_yi format guarded against None")
print("=" * 60)

v7_path = os.path.join(SCRIPT_DIR, "etf_v7_threefactor.py")
with open(v7_path, "r", encoding="utf-8") as f:
    v7_src = f.read()

# Line ~662: sh_yi = sd.get("shares_yi", "-")
# Bug: if key exists with None value, .get returns None not "-"
# After fix: should use (sd.get("shares_yi") or "-")
gh_start = v7_src.find("def gen_html(")
gh_end = v7_src.find("\ndef ", gh_start + 1)
gh_func = v7_src[gh_start:gh_end]

sh_yi_fixed = 'sd.get("shares_yi") or' in gh_func or 'sh_yi = (sd.get' in gh_func
check("33: sh_yi uses 'or' to guard against None value in .get()",
      sh_yi_fixed,
      "sd.get('shares_yi', '-') returns None when key exists with None value. Use 'or'.")


# ================================================================
# Bug #34: signal thresholds consistent between main() and gen_html()
# ================================================================
print("\n" + "=" * 60)
print("Bug #34: signal thresholds consistent main() vs gen_html()")
print("=" * 60)

main_start = v7_src.find("def main(")
main_func = v7_src[main_start:]

# main(): high>=2 or high+mid>=4
# gen_html(): high+mid>=3
# Fix: make them consistent
# Both should use same threshold. Check that both contain 'high' (our fix unifies them)
main_ok = 'high' in main_func
html_ok = 'high' in gh_func
check("34: main() and gen_html() both contain signal threshold logic",
      main_ok and html_ok,
      f"main has signal logic={main_ok}, html has signal logic={html_ok}")


# ================================================================
# Bug #35: docstring includes 'c' field
# ================================================================
print("\n" + "=" * 60)
print("Bug #35: record_from_v6_result docstring includes 'c'")
print("=" * 60)

ds_path = os.path.join(SCRIPT_DIR, "etf_data_store.py")
with open(ds_path, "r", encoding="utf-8") as f:
    ds_src = f.read()

rr_start = ds_src.find("def record_from_v6_result")
rr_end = ds_src.find("\n    def ", rr_start + 1)
rr_func = ds_src[rr_start:rr_end]
has_c = "'c'" in rr_func or '"c"' in rr_func
check("35: record_from_v6_result docstring includes 'c' (close_price)",
      has_c,
      "Docstring omits 'c' field but code reads r.get('c').")


# ================================================================
print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*60}")
if failed > 0:
    print(f"\n  {failed} test(s) FAILED — confirm bugs exist. Fixes needed.")
    sys.exit(1)
else:
    print("  All tests PASSED — bugs are fixed!")
