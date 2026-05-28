# Design: 实盘追踪 + 回测收敛

## #3 实盘追踪
- etf_alert.py: send_email() 成功后写 signal_tracker.json
- scripts/etf_check_results.py: 对比当前价格填充 actual_pnl

## #4 回测收敛
- 保留: backtest_unified.py, backtest_p0_p1.py, etf_backtest_3y.py
- 归档: 其余 8 个回测文件 → scripts/backup/
