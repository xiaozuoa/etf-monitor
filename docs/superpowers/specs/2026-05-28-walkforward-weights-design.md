# Design: Walk-Forward 跌市权重优化

## 目标
在 `w_vol + w_dir + 0.30 = 1.0` 约束下，找最优 `w_dir_down` 值。

## 参数空间
`w_dir_down` ∈ {0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50}
对应 `w_vol_down` = 0.70 - w_dir_down

## 方法
Walk-Forward 滚动窗口：
- 总数据：3 年 800 条日线
- 训练窗：250 天（~1 年），测试窗：60 天（~3 个月）
- 每次滑动 60 天
- 每窗口测试所有 7 个 w_dir_down 值
- 汇总所有窗口的样本外 Sharpe，取均值最高的值

## 实现
新建 `scripts/etf_walkforward_weights.py`，monkey-patch `compute_cp` 的跌市权重，复用 `backtest_unified.run_backtest`。
