# Design: 趋势分级持有期

## 改动

`get_dynamic_params()` 和所有回测 `get_cfg()` 的持有天数：

| 趋势 | 强度 | 原 | 新 |
|------|:---:|:---:|:---:|
| 强上升 | ≥70 | 7 | **12** |
| 上升 | <70 | 7 | **9** |
| 中性 | - | 5 | 6 |
| 下跌 | - | 5 | **4** |

## 改文件

- `scripts/etf_engine.py:673` — `get_dynamic_params()`
- `scripts/backtest_unified.py:13-15` — `get_cfg()`
- `scripts/backtest_p0_p1.py:13-15` — `get_cfg()`
- `scripts/etf_backtest_v4.py:73-86` — 内联 `dynamic` 字典
- `scripts/etf_backtest_allmodels.py:25-55` — 各 `get_config_*()` lambda

备份文件不改。
