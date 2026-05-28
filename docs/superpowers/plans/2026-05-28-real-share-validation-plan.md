# 真实份额验证 实施计划

> **For agentic workers:** Use superpowers:subagent-driven-development

**Goal:** 对比真实份额 vs 模拟份额，验证 30% 权重是否值得

**Architecture:** RealShareCollector 调 akshare 批量下载历史份额，替换 ShareSimulator 跑回测对比

---

### Task 1: 编写并运行真实份额对比脚本

**Files:** Create `scripts/etf_real_share_compare.py`

RealShareCollector:
- 调用 akshare SSE/SZSE API 批量下载历史份额
- 计算真实 delta_pct = (当日份额-前日份额)/前日份额*100
- 实现 get_delta(code, date) → delta_pct

然后跑两次 backtest_unified.run_backtest():
- A: collector=ShareSimulator(data_dict) (模拟)
- B: collector=RealShareCollector(dates) (真实)

对比收益/夏普/回撤。
