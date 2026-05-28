# 趋势分级持有期 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development

**Goal:** 趋势分级持有期 — 强上升12天/上升9天/中性6天/下跌4天

**Architecture:** 改 `get_dynamic_params()` 和所有回测 `get_cfg()` 的 hold_days 数字

---

### Task 1: 改 etf_engine.py（生产核心）

**Files:** Modify `scripts/etf_engine.py:670-676`

- [ ] **Step 1:** 修改 `get_dynamic_params()`

当前：
```python
    if t == "up":
        return {"cp_threshold": 50, "resonance_min": 2, "hold_days": 7, ...}
    else:
        return {"cp_threshold": 50, "resonance_min": 3, "hold_days": 5, ...}
```

改为：
```python
    if t == "up" and trend_info.get("strength", 50) >= 70:
        return {"cp_threshold": 50, "resonance_min": 2, "hold_days": 12, ...}
    elif t == "up":
        return {"cp_threshold": 50, "resonance_min": 2, "hold_days": 9, ...}
    elif t == "down":
        return {"cp_threshold": 50, "resonance_min": 3, "hold_days": 4, ...}
    else:
        return {"cp_threshold": 50, "resonance_min": 3, "hold_days": 6, ...}
```

### Task 2: 改 backtest_unified.py + backtest_p0_p1.py（回测核心）

**Files:** Modify `scripts/backtest_unified.py:13-15`, `scripts/backtest_p0_p1.py:13-15`

`get_cfg(t)`:
```python
    if t == "up":
        return {"cp_threshold": 50, "resonance_min": 2, "hold_days": 9, "allow_pyramiding": True}
    else:
        return {"cp_threshold": 50, "resonance_min": 3, "hold_days": 6, "allow_pyramiding": False}
```

### Task 3: 改 etf_backtest_v4.py + allmodels.py

**Files:** Modify `scripts/etf_backtest_v4.py:73-86`, `scripts/etf_backtest_allmodels.py:25-55`

对应改所有 hold_days 数字。

### Task 4: 回测对比 + 推送
