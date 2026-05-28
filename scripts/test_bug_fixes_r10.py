#!/usr/bin/env python3
"""TDD tests for round 10 — remaining unfixed issues from rounds 1-9."""

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
# Bug #36: backtest_p0_p1.py base position key uses "base" not "510300_base"
# Same bug as Bug#7 — was fixed in 4 other files but missed this one
# ================================================================
print("\n" + "=" * 60)
print("Bug #36: backtest_p0_p1.py base position key")
print("=" * 60)

p0p1_path = os.path.join(SCRIPT_DIR, "backtest_p0_p1.py")
with open(p0p1_path, "r", encoding="utf-8") as f:
    p0p1_src = f.read()

# The holding key for base positions should be "510300_base" not "base"
has_wrong_base_key = 'holding["base"]' in p0p1_src
check("36a: base position uses '510300_base' in holding key not 'base'",
      not has_wrong_base_key,
      "Found holding[\"base\"] — should be holding[\"510300_base\"] for consistency (Bug#7 fix missed this file)")

# Should NOT use bare "base" as holding key anywhere
base_in_holding = 'holding["base"]' in p0p1_src or "holding['base']" in p0p1_src
check("36b: no bare 'base' holding key",
      not base_in_holding,
      "Should use '510300_base' not bare 'base'")


# ================================================================
# Bug #37: get_cfg(t, a) has unused 'a' parameter + broken whitespace
# Affects: backtest_unified.py and backtest_p0_p1.py
# ================================================================
print("\n" + "=" * 60)
print("Bug #37: get_cfg(t, a) dead parameter 'a'")
print("=" * 60)

uni_path = os.path.join(SCRIPT_DIR, "backtest_unified.py")
with open(uni_path, "r", encoding="utf-8") as f:
    uni_src = f.read()

# Check for the weird whitespace in get_cfg
uni_get_cfg = uni_src.split("def get_cfg(")[1].split("\n")[0] if "def get_cfg(" in uni_src else ""
p0p1_get_cfg = p0p1_src.split("def get_cfg(")[1].split("\n")[0] if "def get_cfg(" in p0p1_src else ""

# Both should have clean signatures without large whitespace gaps
uni_clean = "  " not in uni_get_cfg.replace(", ", ",") or len(uni_get_cfg) < 40
p0p1_clean = "  " not in p0p1_get_cfg.replace(", ", ",") or len(p0p1_get_cfg) < 40

check("37a: backtest_unified.py get_cfg has clean signature (no broken whitespace)",
      uni_clean,
      f"get_cfg signature: {uni_get_cfg.strip()}")

check("37b: backtest_p0_p1.py get_cfg has clean signature (no broken whitespace)",
      p0p1_clean,
      f"get_cfg signature: {p0p1_get_cfg.strip()}")

# Check that 'a' parameter is not in the signature (it's unused)
check("37c: backtest_unified.py get_cfg has no unused 'a' parameter",
      "def get_cfg(t," not in uni_src.split("def get_cfg(")[1].split("):")[0] + "a" or
      uni_get_cfg.count(",") <= 1,
      "get_cfg still has unused 'a' parameter")

check("37d: backtest_p0_p1.py get_cfg has no unused 'a' parameter",
      "def get_cfg(t," not in p0p1_src.split("def get_cfg(")[1].split("):")[0] + "a" or
      p0p1_get_cfg.count(",") <= 1,
      "get_cfg still has unused 'a' parameter")


# ================================================================
# Bug #38: backtest_unified.py run_backtest has unused cp_mode parameter
# ================================================================
print("\n" + "=" * 60)
print("Bug #38: backtest_unified.py cp_mode dead parameter")
print("=" * 60)

rb_start = uni_src.find("def run_backtest(")
rb_end = uni_src.find("\ndef ", rb_start + 1)
rb_sig = uni_src[rb_start:rb_end].split("\n")[0] if rb_start >= 0 else ""

check("38: run_backtest has no unused cp_mode parameter",
      "cp_mode" not in rb_sig,
      f"run_backtest signature still has cp_mode: {rb_sig.strip()}")


# ================================================================
# Bug #39: backtest_p0_p1.py CPSystem.__init__ stores self.mode (dead)
# ================================================================
print("\n" + "=" * 60)
print("Bug #39: CPSystem self.mode dead assignment")
print("=" * 60)

cps_init_start = p0p1_src.find("class CPSystem")
cps_init_end = p0p1_src.find("def compute", cps_init_start)
cps_init = p0p1_src[cps_init_start:cps_init_end] if cps_init_start >= 0 else ""

# self.mode should not be present (it's never read)
check("39: CPSystem.__init__ has no dead self.mode assignment",
      "self.mode" not in cps_init,
      "CPSystem.__init__ assigns self.mode but it's never read — dead code")


# ================================================================
print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*60}")
if failed > 0:
    print(f"\n  {failed} test(s) FAILED — confirm bugs exist. Fixes needed.")
    sys.exit(1)
else:
    print("  All tests PASSED — bugs are fixed!")
