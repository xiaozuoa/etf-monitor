# 动态权重 — 跌市方向因子加倍 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修改 `compute_cp()` 根据大盘方向动态调整量能/方向权重，跌市中方向因子翻倍（20%→35%），量能因子降低（50%→35%）

**Architecture:** 只改 `etf_signals.py` 的 `compute_cp()` 函数——所有模块（v7分析、engine、回测）共用此入口。跌市时动态替换权重常量，涨市保持原值不变（零回归风险）。

**Tech Stack:** Python 3, 静态源码检查测试

---

## 文件结构

| 文件 | 角色 | 操作 |
|------|------|------|
| `scripts/etf_signals.py` | CP 计算共享模块 | 修改 `compute_cp()` 函数 ~10行 |
| `scripts/test_dynamic_weights.py` | 动态权重回归测试 | 新建 |

---

### Task 1: 新建测试文件（RED）

**Files:**
- Create: `scripts/test_dynamic_weights.py`

- [ ] **Step 1: 写入测试**

```python
#!/usr/bin/env python3
"""TDD tests for dynamic weights — market-aware CP computation."""

import os, sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from etf_signals import compute_cp, W_VOL, W_DIR, W_SHARE

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
# Test 1: Up market — weights unchanged from original constants
# ================================================================
print("\n" + "=" * 60)
print("Test 1: Up market (idx_chg > 0) — weights unchanged")
print("=" * 60)

# Build minimal test data: 22 days so compute_cp has enough history
# Day 0-20: flat price=5.0, vol=1000000, Day 21: price up 2%, vol=1500000
test_data = []
for i in range(22):
    test_data.append({"date": f"2026-01-{i+1:02d}", "o": 5.0, "c": 5.0, "h": 5.01, "l": 4.99, "v": 1000000})

# Day 21: ETF +2%, volume spike to 1.5M
test_data[21] = {"date": "2026-01-22", "o": 5.0, "c": 5.10, "h": 5.12, "l": 5.00, "v": 1500000}

# Up market: idx_chg = +1%
cp_up, _, _, _, _ = compute_cp(test_data, 21, idx_chg=1.0)

# Down market with same data: idx_chg = -1%
cp_down, _, _, _, _ = compute_cp(test_data, 21, idx_chg=-1.0)

# In down market, direction weight is higher (0.35 vs 0.20)
# An ETF that went up 2% should score HIGHER in a down market (逆势)
check("1a: Down-market CP > up-market CP (逆势ETF gets higher score)",
      cp_down > cp_up,
      f"cp_up={cp_up:.2f}, cp_down={cp_down:.2f}")

check("1b: Both CP values are reasonable (0-100 range)",
      0 <= cp_up <= 100 and 0 <= cp_down <= 100,
      f"cp_up={cp_up:.2f}, cp_down={cp_down:.2f}")

# ================================================================
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
cd D:/airoom/etf-monitor && python scripts/test_dynamic_weights.py
```

预期: exit 1, "1a: Down-market CP > up-market CP" FAIL（目前权重固定，cp_down == cp_up）

- [ ] **Step 3: 确认失败原因正确**

确认 1a FAIL 因为权重未实现动态化，cp_down == cp_up。

---

### Task 2: 实现动态权重（GREEN）

**Files:**
- Modify: `scripts/etf_signals.py:86-106` (`compute_cp` 函数)

- [ ] **Step 1: 修改 compute_cp 函数**

读取 `scripts/etf_signals.py`，找到 `compute_cp` 函数（约第 86-106 行）。

当前代码：
```python
def compute_cp(records, day_i, idx_chg, share_raw=None):
    if share_raw is None:
        share_raw = DEFAULT_SHARE_RAW
    r = records[day_i]
    c, v = r["c"], r["v"]
    chg = (c - records[day_i - 1]["c"]) / records[day_i - 1]["c"] * 100
    vols = [records[j]["v"] for j in range(max(0, day_i - 20), day_i)]
    ma20 = sum(vols) / len(vols) if vols else 1
    vr = v / ma20 if ma20 > 0 else 1
    v_raw = min(1, max(0, (vr - 0.7) / 1.3)) if vr >= 0.7 else 0
    rs, is_c = calc_rs(chg, idx_chg, vr)
    d_raw = rs / 100
    return (v_raw * W_VOL + d_raw * W_DIR + share_raw * W_SHARE) * 100, chg, vr, is_c, c
```

在 `return` 前插入动态权重逻辑，改为：

```python
def compute_cp(records, day_i, idx_chg, share_raw=None):
    if share_raw is None:
        share_raw = DEFAULT_SHARE_RAW
    r = records[day_i]
    c, v = r["c"], r["v"]
    chg = (c - records[day_i - 1]["c"]) / records[day_i - 1]["c"] * 100
    vols = [records[j]["v"] for j in range(max(0, day_i - 20), day_i)]
    ma20 = sum(vols) / len(vols) if vols else 1
    vr = v / ma20 if ma20 > 0 else 1
    v_raw = min(1, max(0, (vr - 0.7) / 1.3)) if vr >= 0.7 else 0
    rs, is_c = calc_rs(chg, idx_chg, vr)
    d_raw = rs / 100

    # 动态权重: 跌市中方向因子翻倍(逆势才是真国家队), 量能降低(跌市放量可能是抛售)
    if idx_chg < 0:
        w_vol, w_dir = 0.35, 0.35
    else:
        w_vol, w_dir = W_VOL, W_DIR

    return (v_raw * w_vol + d_raw * w_dir + share_raw * W_SHARE) * 100, chg, vr, is_c, c
```

- [ ] **Step 2: 语法检查**

```bash
cd D:/airoom/etf-monitor && python -m py_compile scripts/etf_signals.py
```

预期: exit 0

- [ ] **Step 3: 运行新测试 — 验证 PASS**

```bash
cd D:/airoom/etf-monitor && python scripts/test_dynamic_weights.py
```

预期: 2/2 PASS, exit 0

- [ ] **Step 4: Commit**

```bash
cd D:/airoom/etf-monitor && git add scripts/etf_signals.py && git commit -m "feat: compute_cp 动态权重 — 跌市方向因子加倍(20→35%)量能降低(50→35%)"
```

---

### Task 3: 全量回归验证

- [ ] **Step 1: 运行全部测试**

```bash
cd D:/airoom/etf-monitor && for f in scripts/test_bug_fixes*.py scripts/test_etf_fixes.py scripts/test_dynamic_weights.py; do echo "===== $f ====="; python "$f" 2>&1; echo "Exit: $?"; echo; done
```

预期: 全部 PASS, 零回归

- [ ] **Step 2: 运行 v7 分析验证端到端**

```bash
cd D:/airoom/etf-monitor && PYTHONIOENCODING=utf-8 python scripts/etf_v7_threefactor.py --date 2026-05-28 2>&1 | grep -E "(综合判断|Step [67]|CP:)" 
```

预期: 分析完成，无崩溃

- [ ] **Step 3: Commit 测试文件**

```bash
cd D:/airoom/etf-monitor && git add scripts/test_dynamic_weights.py && git commit -m "test: 动态权重回归测试"
```

---

### Task 4: 推送 + 完成

- [ ] **Step 1: 推送**

```bash
cd D:/airoom/etf-monitor && git push origin main
```

- [ ] **Step 2: 验证远端**

```bash
cd D:/airoom/etf-monitor && git log --oneline -3
```
