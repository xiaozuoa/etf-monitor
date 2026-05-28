# Design: 动态权重全覆盖 — 回测文件同步

## 背景

`etf_signals.py:compute_cp()` 已加动态权重（跌市方向 20→35%，量能 50→35%），
但 3 个回测文件使用自有 CP 公式，未同步，导致回测结果与生产信号不一致。

## 改动

### 1. `backtest_unified.py:compute_cp_unified()`

**当前：**
```python
def compute_cp_unified(v_raw, d_raw, code=None, date=None, collector=None):
    ...
    return (v_raw*W_VOL + d_raw*W_DIR + share_raw*W_SHARE)*100
```

**改为：**
```python
def compute_cp_unified(v_raw, d_raw, idx_chg=0, code=None, date=None, collector=None):
    ...
    if idx_chg < 0:
        w_vol, w_dir = 0.35, 0.35
    else:
        w_vol, w_dir = W_VOL, W_DIR
    return (v_raw*w_vol + d_raw*w_dir + share_raw*W_SHARE)*100
```

调用点 `run_backtest()` 传入已计算的 `idx_chg`。

### 2. `backtest_p0_p1.py:CPSystem.compute()`

**当前：**
```python
cp = (v_raw*W_VOL + d_raw*W_DIR + share_raw*W_SHARE)*100
```

**改为：**
```python
if idx_chg < 0:
    w_vol, w_dir = 0.35, 0.35
else:
    w_vol, w_dir = W_VOL, W_DIR
cp = (v_raw*w_vol + d_raw*w_dir + share_raw*W_SHARE)*100
```

`idx_chg` 已是 `compute()` 的参数，无需改签名。

### 3. `etf_backtest_3y.py:105`

**当前：**
```python
cp = (v_raw * 0.50 + d_raw * 0.20 + s_raw * 0.30) * 100
```

**改为：**
```python
w_vol = 0.35 if idx_chg < 0 else etf_signals.W_VOL
w_dir = 0.35 if idx_chg < 0 else etf_signals.W_DIR
cp = (v_raw * w_vol + d_raw * w_dir + s_raw * etf_signals.W_SHARE) * 100
```

同时替换硬编码为共享常量。

## 验证

- 新增 `test_dynamic_weights_full.py`：静态检查 3 个文件是否包含动态权重逻辑
- 运行全部 11 轮测试确认零回归
- 运行 backtest_unified.py 对比改前改后结果
