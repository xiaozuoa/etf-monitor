# Design: 三项收尾修复

## #1 share_raw一致化
compute_cp_unified: 去掉delta*0.7，直接比较原始delta，与full_analysis对齐

## #2 权重网格搜索（W_SHARE=0.20固定）
涨市W_DIR: 0.15/0.20/0.25/0.30/0.35 (W_VOL=0.80-W_DIR)
跌市W_DIR: 0.20/0.25/0.30/0.35/0.40 (W_VOL=0.80-W_DIR)
5×5=25组合，跑全量回测，综合分排序

## #3 v7列对齐
analyze_all: vp=v_raw*100, dp=d_raw*100（与compute_cp内部一致）
