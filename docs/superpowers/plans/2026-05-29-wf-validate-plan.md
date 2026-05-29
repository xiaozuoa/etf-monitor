# 网格搜索 WF 验证 实施计划

> **For agentic workers:** Use superpowers:subagent-driven-development

**Goal:** WF验证TOP5组合是否过拟合

**Architecture:** Monkey-patch compute_cp_unified, WF训练250/测试250/滑动120, 3窗口, 7版本对比样本外Sharpe

**Task:** 建脚本 → 跑WF → 对比排名
