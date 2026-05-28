# Design: v7 CP 计算统一

## 改动
etf_v7_threefactor.py:
- 文件头: from etf_signals import compute_cp
- analyze_all(): CP ← compute_cp(data, i, idchg, share_raw)

## 保留
vp/dp/sp 列仍用原公式(展示用)
