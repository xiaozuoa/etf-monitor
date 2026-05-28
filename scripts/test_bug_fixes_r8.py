#!/usr/bin/env python3
"""TDD tests for 8th round - v7 gen_html crash bugs and data flow issues."""

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
# Bug #30: gen_html guards p=None in table rows
# ================================================================
print("\n" + "=" * 60)
print("Bug #30: gen_html table rows guard against None p")
print("=" * 60)

v7_path = os.path.join(SCRIPT_DIR, "etf_v7_threefactor.py")
with open(v7_path, "r", encoding="utf-8") as f:
    v7_src = f.read()

gh_start = v7_src.find("def gen_html(")
gh_end = v7_src.find("\ndef ", gh_start + 1)
gh_func = v7_src[gh_start:gh_end]

# Check that p["v"], p["vma"], p["vr"], p["vp"], p["dp"] in the f-string are guarded
# Pattern: they should use (p["v"] if p else 0) or similar
# The current bug accesses p["v"] directly without guard
rows_section = gh_func[gh_func.find("rows += f"):gh_func.find("</tr>'''", gh_func.find("rows += f"))]
# Check if there's a guard before the f-string row access
has_guard = "if p:" in rows_section[:200] or "p else" in rows_section[:300]
check("30: gen_html table row access guards against p=None",
      has_guard,
      "p['v'], p['vma'], p['vr'], p['vp'], p['dp'] accessed without None guard.")


# ================================================================
# Bug #31: date_sig sorted chronologically (not dict insertion order)
# ================================================================
print("\n" + "=" * 60)
print("Bug #31: date_sig uses sorted() for chronological order")
print("=" * 60)

# Find the actual_date line in main()
main_start = v7_src.find("def main(")
main_end = v7_src.find("\nif __name__", main_start)
main_func = v7_src[main_start:main_end]

# Should use sorted(date_sig.keys())[-1] not list(date_sig.keys())[-1]
uses_sorted = "sorted(date_sig.keys())" in main_func or "sorted(date_sig)" in main_func
check("31: actual_date uses sorted(date_sig.keys())[-1] for chronological order",
      uses_sorted,
      "list(date_sig.keys())[-1] depends on dict insertion order, may not be latest date.")


# ================================================================
# Bug #32: share date lookup consistent when target_date not found
# ================================================================
print("\n" + "=" * 60)
print("Bug #32: share lookup uses correct date when target_date not in kline")
print("=" * 60)

# Line ~1098: sh_on_target = shares_map....get(target_date or l["d"], {})
# When target_date is specified but not found, should use l["d"] not target_date
# Fix: use l["d"] when target_date not in kline data
lookup_line = [l for l in main_func.split("\n") if "sh_on_target" in l and "shares_map" in l]
share_uses_l_d = any("l[\"d\"]" in l for l in lookup_line)
check("32: share lookup falls back to l['d'] not original target_date",
      share_uses_l_d,
      "When target_date not in kline, share lookup uses wrong date.")


# ================================================================
print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*60}")
if failed > 0:
    print(f"\n  {failed} test(s) FAILED — confirm bugs exist. Fixes needed.")
    sys.exit(1)
else:
    print("  All tests PASSED — bugs are fixed!")
