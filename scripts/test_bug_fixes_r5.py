#!/usr/bin/env python3
"""TDD tests for 5th round of logic bug review."""

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
# Bug #23: record_from_v6_result handles None cp
# ================================================================
print("\n" + "=" * 60)
print("Bug #23: record_from_v6_result handles None cp")
print("=" * 60)

ds_path = os.path.join(SCRIPT_DIR, "etf_data_store.py")
with open(ds_path, "r", encoding="utf-8") as f:
    ds_src = f.read()

# The line: level = "HIGH" if r.get("cp", 0) >= 70 else ...
# Bug: if cp key exists but value is None, r.get("cp", 0) returns None, not 0
# Fix: use (r.get("cp") or 0) or explicit None check
rr_func = ds_src[ds_src.find("def record_from_v6_result"):ds_src.find("\ndef ", ds_src.find("def record_from_v6_result")+1)]
fixed = "or 0)" in rr_func
check("23: record_from_v6_result handles None cp value",
      fixed,
      "r.get('cp',0) returns None when cp key exists with None value. Use (r.get('cp') or 0).")


# ================================================================
# Bug #24: ShareSimulator.get_delta division guarded
# ================================================================
print("\n" + "=" * 60)
print("Bug #24: ShareSimulator get_delta division guarded")
print("=" * 60)

uni_path = os.path.join(SCRIPT_DIR, "backtest_unified.py")
with open(uni_path, "r", encoding="utf-8") as f:
    uni_src = f.read()

ss_start = uni_src.find("class ShareSimulator")
ss_end = uni_src.find("\nclass ", ss_start + 1) if uni_src.find("\nclass ", ss_start + 1) > 0 else uni_src.find("\ndef ", ss_start + 1)
ss = uni_src[ss_start:ss_end] if ss_start >= 0 else ""

# Check if the sum(vols)/len(vols) at the ma20 line has a guard
guarded = "if vols" in ss or "len(vols) > 0" in ss or "if len(vols)" in ss
check("24: ShareSimulator ma20 division guarded",
      guarded,
      "sum(vols)/len(vols) with no guard. ZeroDivisionError if vols empty.")


# ================================================================
# Bug #25: SSE share data type safety
# ================================================================
print("\n" + "=" * 60)
print("Bug #25: SSE share code comparison type-safe")
print("=" * 60)

v7_path = os.path.join(SCRIPT_DIR, "etf_v7_threefactor.py")
with open(v7_path, "r", encoding="utf-8") as f:
    v7_src = f.read()

# Check _fetch_sse_shares for str() conversion on the DataFrame column
sse_func = v7_src[v7_src.find("def _fetch_sse_shares"):v7_src.find("\ndef ", v7_src.find("def _fetch_sse_shares")+1)]
safe_compare = "str(row[" in sse_func or "str(code)" in sse_func or ".astype(str)" in sse_func
check("25a: _fetch_sse_shares uses str() for code comparison",
      safe_compare,
      "df['基金代码'] == code may fail if akshare returns int codes.")

# Check fetch_history_shares_bulk for the same issue
bulk_func = v7_src[v7_src.find("def fetch_history_shares_bulk"):v7_src.find("\ndef ", v7_src.find("def fetch_history_shares_bulk")+1)]
safe_bulk = "str(row[" in bulk_func or "str(code)" in bulk_func or ".astype(str)" in bulk_func
check("25b: fetch_history_shares_bulk uses str() for code comparison",
      safe_bulk,
      "df['基金代码'] == code may fail if akshare returns int codes.")


# ================================================================
print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*60}")
if failed > 0:
    print(f"\n  {failed} test(s) FAILED — confirm bugs exist. Fixes needed.")
    sys.exit(1)
else:
    print("  All tests PASSED — bugs are fixed!")
