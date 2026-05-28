#!/usr/bin/env python3
"""TDD tests for 4th round of logic bug review."""

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
# Bug #20: gen_html dates[-1] PROPERLY guarded (not false positive)
# ================================================================
print("\n" + "=" * 60)
print("Bug #20: gen_html dates[-1] properly guarded against empty")
print("=" * 60)

v7_path = os.path.join(SCRIPT_DIR, "etf_v7_threefactor.py")
with open(v7_path, "r", encoding="utf-8") as f:
    v7_src = f.read()

gh_start = v7_src.find("def gen_html(")
gh_end = v7_src.find("\ndef ", gh_start + 1)
gh_func = v7_src[gh_start:gh_end]

# Check the 10 lines BEFORE dates[-1] for an if-dates guard
v7_lines = v7_src.split("\n")
d1_line = None
for i, line in enumerate(v7_lines):
    if "dates[-1]" in line and "target_date" in line:
        d1_line = i
        break

proper_guard = False
if d1_line:
    for j in range(max(0, d1_line-10), d1_line):
        if "if not dates" in v7_lines[j] or "if dates:" in v7_lines[j].strip():
            proper_guard = True
            break

check("20: gen_html PROPERLY guards dates[-1] against empty list",
      proper_guard,
      "Ternary 'dates else' is NOT a guard against empty dates. Need if dates check.")


# ================================================================
# Bug #21: email stop-loss based on close, not entry
# ================================================================
print("\n" + "=" * 60)
print("Bug #21: stop-loss price notes close-vs-entry mismatch")
print("=" * 60)

# This is a design note, not a code fix. The email says "亏X%就卖" but computes
# sl_price from today's close, while entry is at tomorrow's open.
# Fix: add a note or adjust the price.
alert_path = os.path.join(SCRIPT_DIR, "etf_alert.py")
with open(alert_path, "r", encoding="utf-8") as f:
    alert_src = f.read()

# Check if there's a comment noting the close-vs-open mismatch
has_note = "次日开盘" in alert_src or "明日开盘" in alert_src
check("21: stop-loss email notes entry at tomorrow's open not today's close",
      has_note,
      "sl_price computed from close but entry is at tomorrow's open. Add note.")


# ================================================================
# Bug #22: full_analysis realtime volume inconsistency documented
# ================================================================
print("\n" + "=" * 60)
print("Bug #22: realtime volume inconsistency noted in code")
print("=" * 60)

engine_path = os.path.join(SCRIPT_DIR, "etf_engine.py")
with open(engine_path, "r", encoding="utf-8") as f:
    engine_src = f.read()

fa_start = engine_src.find("def full_analysis(")
fa_end = engine_src.find("\ndef ", fa_start + 1)
fa_func = engine_src[fa_start:fa_end]

# Check for a comment about the realtime vs K-line volume inconsistency
has_note22 = "K线收盘量" in fa_func or "K线量" in fa_func
check("22: full_analysis documents realtime vs K-line volume source",
      has_note22,
      "CP uses K-line volume but display uses realtime volume. Inconsistency undocumented.")


# ================================================================
print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*60}")
if failed > 0:
    print(f"\n  {failed} test(s) FAILED — confirm bugs exist. Fixes needed.")
    sys.exit(1)
else:
    print("  All tests PASSED — bugs are fixed!")
