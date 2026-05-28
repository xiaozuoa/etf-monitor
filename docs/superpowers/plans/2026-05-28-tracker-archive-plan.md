# 实盘追踪 + 回测收敛 实施计划

> **For agentic workers:** Use superpowers:subagent-driven-development

**Goal:** 添加实盘信号追踪 + 清理回测文件

---

### Task 1: 实盘追踪

**Files:** Modify `scripts/etf_alert.py`, Create `scripts/etf_check_results.py`

在 `send_email()` 成功后写 signal_tracker.json。
创建独立的结果检查脚本。

### Task 2: 回测收敛

**Files:** Move 8 files to `scripts/backup/`

保留 backtest_unified.py, backtest_p0_p1.py, etf_backtest_3y.py
