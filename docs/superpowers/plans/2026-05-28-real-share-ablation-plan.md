# 真实份额权重消融 实施计划

> **For agentic workers:** Use superpowers:subagent-driven-development

**Goal:** 用真实份额数据找最优份额权重

**Architecture:** RealShareCollector + 6权重版本 monkey-patch + backtest_unified

---

### Task 1: 编写并运行真实份额消融脚本

**Files:** Create `scripts/etf_real_share_ablation.py`

复用 etf_real_share_compare.py 的 RealShareCollector。
6个版本 (0%/10%/20%/30%/40%/50%)，综合分排序。
