# Design: W_SHARE 30%→20% (真实数据驱动)

## 依据
真实份额消融实验修正版: 20%综合分2.27最优 vs 30%的2.03

## 改动
W_SHARE 0.30→0.20, W_VOL 0.50→0.60
涨市: 50/20/30→60/20/20  跌市: 45/25/30→55/25/20
4个文件: etf_signals.py, backtest_unified.py, backtest_p0_p1.py, etf_backtest_3y.py
