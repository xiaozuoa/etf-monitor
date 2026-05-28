# 第10轮审查修复 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复第10轮审查发现的4个遗漏缺陷：Bug#36 (base key)、Bug#37 (死参数a)、Bug#38 (死参数cp_mode)、Bug#39 (死赋值self.mode)

**Architecture:** 修改2个回测文件 (`backtest_p0_p1.py`, `backtest_unified.py`) 的5+4处代码，新增1个静态检查测试文件。所有缺陷都是死代码/命名不一致问题，无运行时行为变更。

**Tech Stack:** Python 3, 静态源码检查 (grep-style tests, 与前9轮一致)

---

## 文件结构

| 文件 | 角色 | 操作 |
|------|------|------|
| `scripts/backtest_p0_p1.py` | P0 vs P1 回测对比 | 修改5处 |
| `scripts/backtest_unified.py` | P0 统一回测 | 修改4处 |
| `scripts/test_bug_fixes_r10.py` | 第10轮回归测试 | 新建 |

---

### Task 1: 新建 R10 测试文件（RED — 先写失败测试）

**Files:**
- Create: `scripts/test_bug_fixes_r10.py`

- [ ] **Step 1: 写入测试文件（预期全部 FAIL）**

```python
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
# ================================================================
print("\n" + "=" * 60)
print("Bug #36: backtest_p0_p1.py base position key")
print("=" * 60)

p0p1_path = os.path.join(SCRIPT_DIR, "backtest_p0_p1.py")
with open(p0p1_path, "r", encoding="utf-8") as f:
    p0p1_src = f.read()

has_wrong_base_key = 'holding["base"]' in p0p1_src
check("36a: base position uses '510300_base' in holding key not 'base'",
      not has_wrong_base_key,
      "Found holding[\"base\"] — should be holding[\"510300_base\"] for consistency")

base_in_holding = 'holding["base"]' in p0p1_src or "holding['base']" in p0p1_src
check("36b: no bare 'base' holding key anywhere",
      not base_in_holding,
      "Should use '510300_base' not bare 'base'")


# ================================================================
# Bug #37: get_cfg(t, a) has unused 'a' parameter + broken whitespace
# ================================================================
print("\n" + "=" * 60)
print("Bug #37: get_cfg(t, a) dead parameter 'a'")
print("=" * 60)

uni_path = os.path.join(SCRIPT_DIR, "backtest_unified.py")
with open(uni_path, "r", encoding="utf-8") as f:
    uni_src = f.read()

uni_get_cfg = uni_src.split("def get_cfg(")[1].split("\n")[0] if "def get_cfg(" in uni_src else ""
p0p1_get_cfg = p0p1_src.split("def get_cfg(")[1].split("\n")[0] if "def get_cfg(" in p0p1_src else ""

uni_clean = "                                                     " not in uni_get_cfg
p0p1_clean = "                                                     " not in p0p1_get_cfg

check("37a: backtest_unified.py get_cfg has clean signature (no broken whitespace)",
      uni_clean,
      f"get_cfg signature has broken whitespace: ...{uni_get_cfg.strip()[-30:]}")

check("37b: backtest_p0_p1.py get_cfg has clean signature (no broken whitespace)",
      p0p1_clean,
      f"get_cfg signature has broken whitespace: ...{p0p1_get_cfg.strip()[-30:]}")

# 'a' parameter should not appear in get_cfg definition
check("37c: backtest_unified.py get_cfg has no unused 'a' parameter",
      ", a):" not in uni_get_cfg,
      "get_cfg still has unused 'a' parameter")

check("37d: backtest_p0_p1.py get_cfg has no unused 'a' parameter",
      ", a):" not in p0p1_get_cfg,
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
```

- [ ] **Step 2: 运行测试 — 验证全部 FAIL**

```bash
cd D:/airoom/etf-monitor && python scripts/test_bug_fixes_r10.py
```

预期: exit 1, 6-8 FAIL（对应4个未修复的Bug）

- [ ] **Step 3: 确认失败原因正确**

确认每个 FAIL 都因为 Bug 存在（源码中仍有旧代码），而非测试本身 bug。

---

### Task 2: 修复 Bug#37 — get_cfg 死参数 (backtest_unified.py)

**Files:**
- Modify: `scripts/backtest_unified.py:10,113`

- [ ] **Step 1: 修复 get_cfg 签名 + 调用点**

将第 10 行的：
```python
def get_cfg(t,                                                     a):
```
改为：
```python
def get_cfg(t):
```

将第 113 行的：
```python
cfg=get_cfg(t,a)
```
改为：
```python
cfg=get_cfg(t)
```

- [ ] **Step 2: 语法检查**

```bash
cd D:/airoom/etf-monitor && python -m py_compile scripts/backtest_unified.py
```

预期: exit 0, 无输出

- [ ] **Step 3: 运行 R10 测试 — 验证 Bug#37 PASS**

```bash
cd D:/airoom/etf-monitor && python scripts/test_bug_fixes_r10.py
```

预期: 37a 和 37c 从 FAIL→PASS，其余仍 FAIL

- [ ] **Step 4: Commit**

```bash
cd D:/airoom/etf-monitor && git add scripts/backtest_unified.py && git commit -m "fix: Bug#37 backtest_unified.py get_cfg 移除未使用的a参数"
```

---

### Task 3: 修复 Bug#38 — run_backtest cp_mode 死参数 (backtest_unified.py)

**Files:**
- Modify: `scripts/backtest_unified.py:98,272-275,298-299`

- [ ] **Step 1: 修复 run_backtest 签名**

将第 98 行的：
```python
def run_backtest(data_dict, cp_mode, sizing_mode, collector=None):
```
改为：
```python
def run_backtest(data_dict, sizing_mode, collector=None):
```

- [ ] **Step 2: 修复 variants 列表**

将第 272-275 行的：
```python
    variants = [
        ("统一CP(50/20/30,等额)", "unified", "equal"),
        ("统一CP+加权(50/20/30,CP加权)", "unified", "weighted"),
    ]
```
改为：
```python
    variants = [
        ("统一CP(50/20/30,等额)", "equal"),
        ("统一CP+加权(50/20/30,CP加权)", "weighted"),
    ]
```

- [ ] **Step 3: 修复调用循环**

将第 298-299 行的：
```python
        for vname, cp_mode, sizing_mode in variants:
            eq,nt,wr,siglog=run_backtest(precs, cp_mode, sizing_mode, collector)
```
改为：
```python
        for vname, sizing_mode in variants:
            eq,nt,wr,siglog=run_backtest(precs, sizing_mode, collector)
```

- [ ] **Step 4: 语法检查**

```bash
cd D:/airoom/etf-monitor && python -m py_compile scripts/backtest_unified.py
```

预期: exit 0

- [ ] **Step 5: 运行 R10 测试 — 验证 Bug#38 PASS**

```bash
cd D:/airoom/etf-monitor && python scripts/test_bug_fixes_r10.py
```

预期: Bug#37(全部)+#38 PASS，Bug#36+#39 仍 FAIL

- [ ] **Step 6: Commit**

```bash
cd D:/airoom/etf-monitor && git add scripts/backtest_unified.py && git commit -m "fix: Bug#38 backtest_unified.py run_backtest 移除未使用的cp_mode参数"
```

---

### Task 4: 修复 Bug#37 — get_cfg 死参数 (backtest_p0_p1.py)

**Files:**
- Modify: `scripts/backtest_p0_p1.py:10,100`

- [ ] **Step 1: 修复 get_cfg 签名 + 调用点**

将第 10 行的：
```python
def get_cfg(t,                                                     a):
```
改为：
```python
def get_cfg(t):
```

将第 100 行的：
```python
cfg=get_cfg(t,a)
```
改为：
```python
cfg=get_cfg(t)
```

- [ ] **Step 2: 语法检查**

```bash
cd D:/airoom/etf-monitor && python -m py_compile scripts/backtest_p0_p1.py
```

- [ ] **Step 3: 运行 R10 测试 — 验证 Bug#37d PASS**

```bash
cd D:/airoom/etf-monitor && python scripts/test_bug_fixes_r10.py
```

预期: Bug#37(全部)+#38 PASS，Bug#36+#39 仍 FAIL

- [ ] **Step 4: Commit**

```bash
cd D:/airoom/etf-monitor && git add scripts/backtest_p0_p1.py && git commit -m "fix: Bug#37 backtest_p0_p1.py get_cfg 移除未使用的a参数"
```

---

### Task 5: 修复 Bug#39 — CPSystem self.mode 死赋值 (backtest_p0_p1.py)

**Files:**
- Modify: `scripts/backtest_p0_p1.py:37-39,265`

- [ ] **Step 1: 修复 CPSystem.__init__**

将第 37-41 行的：
```python
class CPSystem:
    def __init__(self, mode, data_dict):
        self.mode = mode  # 'baseline' | 'p0' | 'p1' | 'p0p1'
        self.data_dict = data_dict
        self._share_cache = {}
```
改为：
```python
class CPSystem:
    def __init__(self, data_dict):
        self.data_dict = data_dict
        self._share_cache = {}
```

- [ ] **Step 2: 修复调用点**

将第 265 行的：
```python
cp_sys=CPSystem(vmode, data_dict)
```
改为：
```python
cp_sys=CPSystem(data_dict)
```

- [ ] **Step 3: 语法检查**

```bash
cd D:/airoom/etf-monitor && python -m py_compile scripts/backtest_p0_p1.py
```

- [ ] **Step 4: 运行 R10 测试 — 验证 Bug#39 PASS**

```bash
cd D:/airoom/etf-monitor && python scripts/test_bug_fixes_r10.py
```

预期: Bug#37+#38+#39 PASS，仅 Bug#36 仍 FAIL

- [ ] **Step 5: Commit**

```bash
cd D:/airoom/etf-monitor && git add scripts/backtest_p0_p1.py && git commit -m "fix: Bug#39 backtest_p0_p1.py CPSystem 移除未使用的mode参数"
```

---

### Task 6: 修复 Bug#36 — base 持仓 key (backtest_p0_p1.py)

**Files:**
- Modify: `scripts/backtest_p0_p1.py:125`

- [ ] **Step 1: 修复 holding key**

将第 125 行的：
```python
holding["base"]={"shares":sh,"cost":cost,"entry_price":bp,"entry_date":ref[ni]["date"],"entry_i":ni,"highest":bp,"is_base":True}
```
改为：
```python
holding["510300_base"]={"shares":sh,"cost":cost,"entry_price":bp,"entry_date":ref[ni]["date"],"entry_i":ni,"highest":bp,"is_base":True}
```

- [ ] **Step 2: 语法检查**

```bash
cd D:/airoom/etf-monitor && python -m py_compile scripts/backtest_p0_p1.py
```

- [ ] **Step 3: 运行 R10 测试 — 验证全部 PASS**

```bash
cd D:/airoom/etf-monitor && python scripts/test_bug_fixes_r10.py
```

预期: 8/8 PASS, exit 0

- [ ] **Step 4: Commit**

```bash
cd D:/airoom/etf-monitor && git add scripts/backtest_p0_p1.py && git commit -m "fix: Bug#36 backtest_p0_p1.py holding base key→510300_base (Bug#7遗漏)"
```

---

### Task 7: 全量回归验证

- [ ] **Step 1: 运行全部测试轮**

```bash
cd D:/airoom/etf-monitor && for f in scripts/test_bug_fixes*.py scripts/test_etf_fixes.py; do echo "===== $f ====="; python "$f" 2>&1; echo "Exit: $?"; echo; done
```

预期: 全部 10 轮 ~62 测试 PASS, 所有 exit 0

- [ ] **Step 2: 最终验证 — 无新增问题**

```bash
cd D:/airoom/etf-monitor && git diff --stat HEAD~4..HEAD
```

确认只改了 `backtest_p0_p1.py` 和 `backtest_unified.py`，以及新增 `test_bug_fixes_r10.py`

- [ ] **Step 3: Commit 测试文件**

```bash
cd D:/airoom/etf-monitor && git add scripts/test_bug_fixes_r10.py && git commit -m "test: 新增R10回归测试 — 4项遗漏修复验证"
```
