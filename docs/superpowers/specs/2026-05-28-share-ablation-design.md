# Design: 份额因子消融实验

## 方法
Monkey-patch compute_cp + compute_cp_unified，不修改生产代码。
3 个版本对比 3 年全量回测。

## 版本
A (当前): 涨市50/20/30 跌市45/25/30
B (去份额): 涨市70/30/0 跌市65/35/0
C (翻倍): 涨市35/15/50 跌市30/20/50

## 判断
综合得分 = Sharpe×2 + 收益率/100 - |回撤|/50

## 新建文件
scripts/etf_share_ablation.py — 一次性实验脚本，跑完不保留
