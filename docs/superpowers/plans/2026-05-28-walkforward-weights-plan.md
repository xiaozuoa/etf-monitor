# Walk-Forward 跌市权重优化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development

**Goal:** 在 w_vol + w_dir + 0.30 = 1.0 约束下，Walk-Forward 验证找最优 w_dir_down

**Architecture:** Monkey-patch `etf_signals.compute_cp` 的跌市权重，复用 `backtest_unified.run_backtest`，滚动窗口遍历 7 个候选值

**Tech Stack:** Python 3, etf_signals, backtest_unified

---

## 文件结构

| 文件 | 角色 | 操作 |
|------|------|------|
| `scripts/etf_walkforward_weights.py` | WF 权重搜索脚本 | 新建 |

---

### Task 1: Walk-Forward 权重搜索

**Files:**
- Create: `scripts/etf_walkforward_weights.py`

- [ ] **Step 1: 写入脚本**

```python
#!/usr/bin/env python3
"""Walk-Forward: 找最优跌市权重 (w_dir_down)"""

import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from etf_signals import fetch, detect_trend, calc_rs, W_VOL, W_DIR, W_SHARE, DEFAULT_SHARE_RAW, COMMISSION, SLIPPAGE, INITIAL
from backtest_unified import run_backtest as _run_backtest, ShareSimulator

# Monkey-patch compute_cp with configurable w_dir_down
import etf_signals
_orig_cp = etf_signals.compute_cp
import backtest_unified
_orig_cpu = backtest_unified.compute_cp_unified

def make_patched_compute_cp(w_dir_down):
    w_vol_down = 0.70 - w_dir_down
    def patched(records, day_i, idx_chg, share_raw=None):
        if share_raw is None: share_raw = DEFAULT_SHARE_RAW
        r = records[day_i]
        chg = (r['c'] - records[day_i - 1]['c']) / records[day_i - 1]['c'] * 100
        vols = [records[j]['v'] for j in range(max(0, day_i - 20), day_i)]
        ma20 = sum(vols) / len(vols) if vols else 1
        vr = r['v'] / ma20 if ma20 > 0 else 1
        v_raw = min(1, max(0, (vr - 0.7) / 1.3)) if vr >= 0.7 else 0
        rs, is_c = calc_rs(chg, idx_chg, vr)
        d_raw = rs / 100
        if idx_chg < 0:
            wv, wd = w_vol_down, w_dir_down
        else:
            wv, wd = W_VOL, W_DIR
        return (v_raw * wv + d_raw * wd + share_raw * W_SHARE) * 100, chg, vr, is_c, r['c']
    return patched

def make_patched_cp_unified(w_dir_down):
    w_vol_down = 0.70 - w_dir_down
    def patched(v_raw, d_raw, idx_chg=0, code=None, date=None, collector=None):
        share_raw = DEFAULT_SHARE_RAW
        if collector is not None and code is not None and date is not None:
            delta = collector.get_delta(code, date)
            if delta is not None:
                dp = delta*0.7
                if dp>0.5: share_raw = min(1.0, 0.12+dp*0.06)
                elif dp<-1: share_raw = max(0.0, 0.12+dp*0.03)
                share_raw = max(0,min(1,share_raw))
        if idx_chg < 0:
            wv, wd = w_vol_down, w_dir_down
        else:
            wv, wd = W_VOL, W_DIR
        return (v_raw*wv + d_raw*wd + share_raw*W_SHARE)*100
    return patched


print("=" * 70)
print("Walk-Forward: 跌市权重优化 (w_dir_down)")
print("=" * 70)

# 拉数据
print("\n拉取15只ETF K线...")
data_dict = {}
from etf_engine import ETFS
for code in ETFS:
    data_dict[code] = fetch(code, 800)
ref = data_dict["510300"]
rdates = [r["date"] for r in ref]
print(f"  数据: {rdates[0]} ~ {rdates[-1]} ({len(ref)}条)")

# WF 参数
TRAIN = 250  # 1年
TEST = 60    # 3个月
STEP = 60    # 滑动步长

w_dir_candidates = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
results = {w: [] for w in w_dir_candidates}

total_windows = 0
win_start = 60  # 最小预热
while win_start + TRAIN + TEST < len(ref):
    train_si = win_start
    train_ei = win_start + TRAIN
    test_si = train_ei
    test_ei = min(test_si + TEST, len(ref) - 13)
    if test_ei <= test_si + 30:
        break

    test_data = {}
    for c in data_dict:
        dlist = data_dict[c]
        if test_ei < len(dlist):
            test_data[c] = dlist[test_si:test_ei + 1]
    if "510300" not in test_data or len(test_data["510300"]) < 30:
        win_start += STEP
        continue

    total_windows += 1

    for w_dir in w_dir_candidates:
        etf_signals.compute_cp = make_patched_compute_cp(w_dir)
        backtest_unified.compute_cp_unified = make_patched_cp_unified(w_dir)

        collector = ShareSimulator(test_data)
        eq, nt, wr, _ = _run_backtest(test_data, "equal", collector)
        if len(eq) < 2:
            results[w_dir].append(None)
            continue

        # 计算样本外 Sharpe
        dr = [(eq[i]/eq[i-1]-1) for i in range(1, len(eq))]
        if dr and sum(dr)/len(dr) > 0:
            sh = (sum(dr)/len(dr)) / ((sum((r-sum(dr)/len(dr))**2 for r in dr)/len(dr))**0.5) * (252**0.5)
        else:
            sh = 0
        # 也记收益
        ret = (eq[-1]/eq[0]-1)*100
        results[w_dir].append({"sharpe": round(sh, 2), "return": round(ret, 1), "trades": nt})

    # 恢复
    etf_signals.compute_cp = _orig_cp
    backtest_unified.compute_cp_unified = _orig_cpu

    win_start += STEP

print(f"\n完成 {total_windows} 个测试窗口\n")

# 汇总
print(f"{'w_dir':<10} {'样本外均值Sharpe':>16} {'均值收益':>10} {'均值交易':>10} {'有效窗口':>8}")
print("-" * 56)
best_w, best_sh = 0.35, -999
for w_dir in w_dir_candidates:
    valid = [r for r in results[w_dir] if r is not None]
    if not valid:
        continue
    avg_sh = sum(r["sharpe"] for r in valid) / len(valid)
    avg_ret = sum(r["return"] for r in valid) / len(valid)
    avg_nt = sum(r["trades"] for r in valid) / len(valid)
    marker = " <<<" if avg_sh > best_sh else ""
    if avg_sh > best_sh:
        best_sh = avg_sh
        best_w = w_dir
    print(f"  {w_dir:.2f}      {avg_sh:>14.2f}    {avg_ret:>+8.1f}%  {avg_nt:>8.1f}     {len(valid):>4}{marker}")

print(f"\n最优: w_dir_down = {best_w:.2f}, w_vol_down = {0.70-best_w:.2f}")
print(f"样本外 Sharpe 均值: {best_sh:.2f}")
```

- [ ] **Step 2: 运行**

```bash
cd D:/airoom/etf-monitor && PYTHONIOENCODING=utf-8 python scripts/etf_walkforward_weights.py
```

- [ ] **Step 3: 根据结果更新 etf_signals.py 中的 0.35→最优值**

- [ ] **Step 4: Commit + push**
