# Design: v7 CP 计算统一

## 改动

`etf_v7_threefactor.py:analyze_all()` — CP 改用 `etf_signals.compute_cp()`

改前：vp/dp/sp 各自加权 `vp*0.5 + dp*0.2 + sp*0.3`
改后：调用 `compute_cp(data, i, idchg, share_raw)` 获得统一 CP

## 子因子列保留

vp/dp/sp 列仍用原 vprob/dprob/sprob 计算（纯展示，不影响 CP）

## share_raw 转换

用 engine 同等公式：delta_pct → share_raw
