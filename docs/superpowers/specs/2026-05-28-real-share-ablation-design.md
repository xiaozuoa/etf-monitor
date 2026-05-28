# Design: 真实份额权重消融

## 方法
RealShareCollector + 6个权重版本 0%/10%/20%/30%/40%/50%
方向权重恒定，只变份额

## 判断
综合分 = Sharpe×2 + 收益/100 - |回撤|/50

## 临时脚本
etf_real_share_ablation.py — 一次性实验
