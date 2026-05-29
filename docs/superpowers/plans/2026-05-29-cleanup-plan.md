# 三项收尾修复 实施计划

> **For agentic workers:** Use superpowers:subagent-driven-development

**Goal:** share_raw一致化 + 权重网格搜索 + v7列对齐

---

### Task 1: #1 share_raw一致化
backtest_unified.py compute_cp_unified: dp=delta*0.7 → dp=delta
去掉0.7折扣，与full_analysis对齐

### Task 2: #2 权重网格搜索
建临时脚本 etf_weight_grid_search.py:
- W_SHARE=0.20固定
- 涨市W_DIR: 0.15/0.20/0.25/0.30/0.35
- 跌市W_DIR: 0.20/0.25/0.30/0.35/0.40
- 25组合跑全量回测，综合分排序
- 最优解更新到代码

### Task 3: #3 v7列对齐
etf_v7_threefactor.py analyze_all:
vp=v_raw*100, dp=d_raw*100
