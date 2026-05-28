# 动态权重全覆盖 — 回测文件同步 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将动态权重逻辑同步到 3 个回测文件的 CP 计算函数中，使回测结果与生产信号一致

**Architecture:** 每个文件加同样的 4 行 `if idx_chg < 0` 判断。`backtest_unified.py` 需额外加 `idx_chg` 参数，其余两个已有该变量

**Tech Stack:** Python 3, 静态源码检查测试

---

## 文件结构

| 文件 | 角色 | 操作 |
|------|------|------|
| `scripts/backtest_unified.py` | P0统一回测 | 修改 `compute_cp_unified()` + 调用点 |
| `scripts/backtest_p0_p1.py` | P0/P1对比回测 | 修改 `CPSystem.compute()` |
| `scripts/etf_backtest_3y.py` | 3年回测 | 修改内联 CP 行 |
| `scripts/test_dynamic_weights_full.py` | 全覆盖回归测试 | 新建 |

---

### Task 1: 新建全覆盖测试（RED）

**Files:**
- Create: `scripts/test_dynamic_weights_full.py`

- [ ] **Step 1: 写入测试文件**

```python
#!/usr/bin/env python3
"""TDD tests: dynamic weights in ALL CP computation points."""

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

def get_func_body(src, func_name):
    start = src.find(f"def {func_name}(")
    if start == -1:
        return ""
    end = src.find("\ndef ", start + 1)
    if end == -1:
        end = src.find("\nclass ", start + 1)
    if end == -1:
        end = len(src)
    return src[start:end]


print("=" * 60)
print("Dynamic weights coverage audit")
print("=" * 60)

# File 1: etf_signals.py (already has it, baseline check)
sig_path = os.path.join(SCRIPT_DIR, "etf_signals.py")
with open(sig_path, "r", encoding="utf-8") as f:
    sig_src = f.read()
cp_body = get_func_body(sig_src, "compute_cp")
check("0: etf_signals.py compute_cp has dynamic weights (baseline)",
      "idx_chg < 0" in cp_body and "0.35" in cp_body,
      "Baseline already implemented")

# File 2: backtest_unified.py
uni_path = os.path.join(SCRIPT_DIR, "backtest_unified.py")
with open(uni_path, "r", encoding="utf-8") as f:
    uni_src = f.read()
uni_body = get_func_body(uni_src, "compute_cp_unified")
check("1a: backtest_unified.py compute_cp_unified has idx_chg parameter",
      "idx_chg" in uni_body.split("):")[0] if "):" in uni_body else False,
      "compute_cp_unified needs idx_chg parameter for dynamic weights")
check("1b: backtest_unified.py compute_cp_unified has dynamic weight logic",
      "idx_chg < 0" in uni_body and "0.35" in uni_body,
      "compute_cp_unified missing dynamic weight switching")

# File 3: backtest_p0_p1.py
p0p1_path = os.path.join(SCRIPT_DIR, "backtest_p0_p1.py")
with open(p0p1_path, "r", encoding="utf-8") as f:
    p0p1_src = f.read()
cps_start = p0p1_src.find("class CPSystem")
cps_end = p0p1_src.find("\nclass ", cps_start + 1)
if cps_end == -1:
    cps_end = p0p1_src.find("\ndef run_backtest", cps_start + 1)
if cps_end == -1:
    cps_end = len(p0p1_src)
cps_body = p0p1_src[cps_start:cps_end]
check("2: backtest_p0_p1.py CPSystem.compute has dynamic weight logic",
      "idx_chg < 0" in cps_body and "0.35" in cps_body,
      "CPSystem.compute missing dynamic weight switching")

# File 4: etf_backtest_3y.py
bt3_path = os.path.join(SCRIPT_DIR, "etf_backtest_3y.py")
with open(bt3_path, "r", encoding="utf-8") as f:
    bt3_src = f.read()
check("3a: etf_backtest_3y.py no hardcoded 0.50/0.20/0.30 weights",
      "0.50 + d_raw * 0.20 + s_raw * 0.30" not in bt3_src,
      "Still uses hardcoded fixed weights instead of dynamic")
check("3b: etf_backtest_3y.py has dynamic weight logic",
      "idx_chg < 0" in bt3_src and "0.35" in bt3_src,
      "etf_backtest_3y.py missing dynamic weight switching")


print(f"\n{'='*60}")
print(f"Results: {passed} passed, {failed} failed out of {passed+failed}")
print(f"{'='*60}")
if failed > 0:
    print(f"\n  {failed} test(s) FAILED.")
    sys.exit(1)
else:
    print("  All tests PASSED!")
```

- [ ] **Step 2: 运行测试 — 验证 FAIL**

```bash
cd D:/airoom/etf-monitor && python scripts/test_dynamic_weights_full.py
```

预期: exit 1, 1a/1b/2/3a/3b FAIL（5 个未覆盖点），0 号 PASS（基线已有）

---

### Task 2: 修复 backtest_p0_p1.py（GREEN — 最简单，idx_chg 已有）

**Files:**
- Modify: `scripts/backtest_p0_p1.py:57`

- [ ] **Step 1: 加动态权重**

找到 `CPSystem.compute()` 中的：
```python
        cp = (v_raw*W_VOL + d_raw*W_DIR + share_raw*W_SHARE)*100
```
替换为：
```python
        if idx_chg < 0:
            w_vol, w_dir = 0.35, 0.35
        else:
            w_vol, w_dir = W_VOL, W_DIR
        cp = (v_raw*w_vol + d_raw*w_dir + share_raw*W_SHARE)*100
```

- [ ] **Step 2: 验证**

```bash
cd D:/airoom/etf-monitor && python -m py_compile scripts/backtest_p0_p1.py && python scripts/test_dynamic_weights_full.py
```

- [ ] **Step 3: Commit**

```bash
cd D:/airoom/etf-monitor && git add scripts/backtest_p0_p1.py && git commit -m "fix: backtest_p0_p1.py CPSystem.compute 加动态权重"
```

---

### Task 3: 修复 backtest_unified.py（GREEN — 需加 idx_chg 参数）

**Files:**
- Modify: `scripts/backtest_unified.py:22,32,167`

- [ ] **Step 1: 修改函数签名 + 函数体**

`compute_cp_unified` 签名行改为：
```python
def compute_cp_unified(v_raw, d_raw, idx_chg=0, code=None, date=None, collector=None):
```

函数体 return 前插入：
```python
    if idx_chg < 0:
        w_vol, w_dir = 0.35, 0.35
    else:
        w_vol, w_dir = W_VOL, W_DIR
```

return 行改为：
```python
    return (v_raw*w_vol + d_raw*w_dir + share_raw*W_SHARE)*100
```

- [ ] **Step 2: 修改调用点**

`run_backtest()` 中调用改为：
```python
            cp = compute_cp_unified(v_raw, d_raw, idx_chg, code, date, collector or ShareSimulator(data_dict))
```

- [ ] **Step 3: 验证**

```bash
cd D:/airoom/etf-monitor && python -m py_compile scripts/backtest_unified.py && python scripts/test_dynamic_weights_full.py
```

- [ ] **Step 4: Commit**

```bash
cd D:/airoom/etf-monitor && git add scripts/backtest_unified.py && git commit -m "fix: backtest_unified.py compute_cp_unified 加动态权重 + idx_chg参数"
```

---

### Task 4: 修复 etf_backtest_3y.py（GREEN — 替换硬编码）

**Files:**
- Modify: `scripts/etf_backtest_3y.py:104-105`

- [ ] **Step 1: 替换硬编码为动态权重**

找到：
```python
            s_raw = 0.12
            cp = (v_raw * 0.50 + d_raw * 0.20 + s_raw * 0.30) * 100
```
替换为：
```python
            s_raw = 0.12
            if idx_chg < 0:
                w_vol, w_dir = 0.35, 0.35
            else:
                w_vol, w_dir = etf_signals.W_VOL, etf_signals.W_DIR
            cp = (v_raw * w_vol + d_raw * w_dir + s_raw * etf_signals.W_SHARE) * 100
```

- [ ] **Step 2: 验证**

```bash
cd D:/airoom/etf-monitor && python -m py_compile scripts/etf_backtest_3y.py && python scripts/test_dynamic_weights_full.py
```

预期: 全部 PASS

- [ ] **Step 3: Commit**

```bash
cd D:/airoom/etf-monitor && git add scripts/etf_backtest_3y.py && git commit -m "fix: etf_backtest_3y.py 替换硬编码权重为动态权重+共享常量"
```

---

### Task 5: 全量回归 + 回测对比 + 推送

- [ ] **Step 1: 运行全部测试**

```bash
cd D:/airoom/etf-monitor && for f in scripts/test_bug_fixes*.py scripts/test_etf_fixes.py scripts/test_dynamic_weights*.py; do echo "===== $f ====="; python "$f" 2>&1; echo "Exit: $?"; echo; done
```

- [ ] **Step 2: 运行 P0 统一回测看对比**

```bash
cd D:/airoom/etf-monitor && PYTHONIOENCODING=utf-8 python scripts/backtest_unified.py 2>&1
```

- [ ] **Step 3: Commit 测试文件 + 推送**

```bash
cd D:/airoom/etf-monitor && git add scripts/test_dynamic_weights_full.py && git commit -m "test: 动态权重全覆盖回归测试" && git push origin main
```
