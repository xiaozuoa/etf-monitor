# v7 CP 统一 实施计划

> **For agentic workers:** Use superpowers:subagent-driven-development

**Goal:** v7 analyze_all() CP 改用 etf_signals.compute_cp()

**Architecture:** 加 import + 替换 CP 计算行

---

### Task 1: TDD — 写测试验证 v7 CP 与 engine CP 不一致(RED)

Create `scripts/test_v7_unify.py` — 调用 analyze_all 和 compute_cp，对比 CP，预期 FAIL

### Task 2: 实现统一(GREEN)

- etf_v7_threefactor.py: 加 `from etf_signals import compute_cp`
- analyze_all(): 替换 cp = vp*0.5+dp*0.2+sp*0.3 → compute_cp()

### Task 3: 验证 + 提交
