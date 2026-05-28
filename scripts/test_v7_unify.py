#!/usr/bin/env python3
"""TDD: v7 analyze_all CP should match etf_signals.compute_cp"""
import os, sys
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from etf_signals import fetch, compute_cp
from etf_v7_threefactor import analyze_all

passed = 0
failed = 0
def check(name, condition, detail=""):
    global passed, failed
    if condition: passed += 1; print(f"  PASS: {name}")
    else: failed += 1; print(f"  FAIL: {name}  -- {detail}")

print("=" * 60)
print("v7 CP Unification Test")
print("=" * 60)

# Get data
data = fetch('510300', 60)
idx = fetch('sh000300', 60)

if data and idx:
    results = analyze_all(data, idx, {}, 35, code='510300')
    if results:
        latest = results[-1]
        idchg = latest['idx_chg']
        engine_cp, _, _, _, _ = compute_cp(data, len(data)-1, idchg)

        v7_cp = latest['cp']
        print(f"  v7 CP: {v7_cp}")
        print(f"  engine CP: {engine_cp:.1f}")
        match = abs(v7_cp - engine_cp) < 0.15

        check("v7 CP matches engine compute_cp", match,
              f"Difference: v7={v7_cp} vs engine={engine_cp:.1f}")

print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed")
print(f"{'='*60}")
if failed > 0:
    print("RED: v7 CP NOT unified yet — proceed to GREEN")
    sys.exit(1)
else:
    print("GREEN: v7 CP unified!")
