# Design: 实盘追踪 + 回测收敛

## #3 实盘追踪
- etf_alert.py: send_email()成功后写signal_tracker.json
- etf_check_results.py: 读取tracker，对比当前价算实际盈亏

## #4 回测收敛
- 保留: backtest_unified.py, backtest_p0_p1.py, etf_backtest_3y.py
- 归档至backup/: 其余8个回测文件
- 测试路径同步更新
