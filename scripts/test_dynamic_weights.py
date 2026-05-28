#!/usr/bin/env python3
"""TDD tests for dynamic weights — market-aware CP computation."""

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


print("=" * 60)
print("Dynamic Weights: compute_cp uses market-aware weight switching")
print("=" * 60)

signals_path = os.path.join(SCRIPT_DIR, "etf_signals.py")
with open(signals_path, "r", encoding="utf-8") as f:
    src = f.read()

# Extract compute_cp function body
cp_start = src.find("def compute_cp(")
cp_end = src.find("\ndef ", cp_start + 1)
if cp_end == -1:
    cp_end = len(src)
cp_body = src[cp_start:cp_end]

# Check 1: Contains idx_chg < 0 condition for weight switching
check("1a: compute_cp checks idx_chg < 0 for weight switching",
      "idx_chg < 0" in cp_body,
      "compute_cp should check market direction to switch weights")

# Check 2: Contains the new weight value 0.35 for down market
check("1b: Down-market uses weight 0.35 (lowered vol, raised dir)",
      "0.35" in cp_body,
      "Down market should use 0.35 for both vol and dir weights")

# Check 3: Contains W_VOL reference for up-market (keeping original constant)
check("1c: Up-market still references W_VOL (keeps original 0.50)",
      "W_VOL" in cp_body,
      "Up market should use original W_VOL constant")

# Check 4: Contains W_DIR reference for up-market
check("1d: Up-market still references W_DIR (keeps original 0.20)",
      "W_DIR" in cp_body,
      "Up market should use original W_DIR constant")


print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*60}")
if failed > 0:
    print(f"\n  {failed} test(s) FAILED — dynamic weights NOT yet implemented.")
    sys.exit(1)
else:
    print("  All tests PASSED — dynamic weights implemented!")
