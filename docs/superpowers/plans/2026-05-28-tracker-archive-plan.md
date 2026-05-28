# 实盘追踪 + 回测收敛 实施计划

> **For agentic workers:** Use superpowers:subagent-driven-development

**Goal:** 添加实盘信号追踪 + 清理回测文件目录

**Architecture:** 两个独立改动并行执行

---

### Task 1: 实盘追踪

**Files:** Modify `scripts/etf_alert.py`, Create `scripts/etf_check_results.py`

- etf_alert.py send_email()成功后写signal_tracker.json
- etf_check_results.py读取tracker对比实际盈亏

### Task 2: 回测收敛

**Files:** git mv 8个文件到scripts/backup/，更新test_bug_fixes引用路径

- 保留: backtest_unified.py, backtest_p0_p1.py, etf_backtest_3y.py
- 归档: 其余8个
- 更新test_bug_fixes_r2.py, r6.py中的路径引用
