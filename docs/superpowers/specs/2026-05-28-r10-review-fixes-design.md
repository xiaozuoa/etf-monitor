# Design: 第10轮审查 — 4项遗漏修复

## 背景

前9轮代码审查修复了35个Bug，全部有测试验证。但第10轮全量扫描发现4个遗漏，都源于 2026-05-28 简化重构（4状态→2状态、权重统一）后的残留清理不完整。

## 缺陷清单

### Bug#36: backtest_p0_p1.py 底仓 key 遗漏 (`holding["base"]`)
- **行**: 125
- **根因**: Bug#7 在 4 个回测文件中将 `"base"` 改为 `"510300_base"`，遗漏了 `backtest_p0_p1.py`
- **影响**: 低 — 双重 `.get()` 回退机制侥幸工作，但与其他 4 个回测文件不一致
- **修复**: `holding["base"]` → `holding["510300_base"]`

### Bug#37: get_cfg(t, a) 死参数
- **行**: backtest_unified.py:10, backtest_p0_p1.py:10
- **根因**: 4→2 状态简化后 `a` (above_ma) 不再被函数体使用，但签名未清理，且留有破损空白符
- **影响**: 低 — 仅代码质量问题，不影响运行
- **修复**: `def get_cfg(t, a):` → `def get_cfg(t):`，清理破损空白符；调用点同步更新

### Bug#38: run_backtest cp_mode 死参数
- **行**: backtest_unified.py:98
- **根因**: CP 公式统一为 50/20/30 后，函数始终使用 `compute_cp_unified`，`cp_mode` 不再有分支意义
- **影响**: 低 — 仅代码质量问题
- **修复**: 从函数签名、variants 列表、调用循环中移除 `cp_mode`

### Bug#39: CPSystem self.mode 死赋值
- **行**: backtest_p0_p1.py:38-39
- **根因**: `__init__` 存储 `self.mode = mode`，但 `compute()` 方法从不读取
- **影响**: 低 — 仅代码质量问题
- **修复**: 移除 `mode` 参数和 `self.mode = mode` 赋值；调用点 `CPSystem(vmode, data_dict)` → `CPSystem(data_dict)`

## 修改范围

| 文件 | 改动数 | 类型 |
|------|--------|------|
| `scripts/backtest_p0_p1.py` | 5处 | 修复 Bug#36, #37, #39 |
| `scripts/backtest_unified.py` | 4处 | 修复 Bug#37, #38 |
| `scripts/test_bug_fixes_r10.py` | 新增 | 回归测试 (4组静态检查) |

## 不做

- 不修改生产文件（缺陷全在回测文件）
- 不清理 `compute_cp_unified` 的 `collector or ShareSimulator(...)` 回退 — 保留可独立测试性
- 不修改 `variant_name` 参数（`backtest_p0_p1.py` 的 `run_backtest` 确实使用 `variant_name` 做 P1 分支）

## 测试策略

新建 `test_bug_fixes_r10.py`，4 组静态检查：
- **36**: 全项目无 `holding["base"]` 裸 key
- **37**: `get_cfg` 签名不含 `a` 参数，无破损空白符
- **38**: `run_backtest` 签名不含 `cp_mode`
- **39**: `CPSystem.__init__` 不含 `self.mode`

沿用前 9 轮模式：静态源码检查 + exit code 验证。

## 验证

- 运行全部 10 轮测试（~62 项）：100% 通过
- Python 语法检查：2 个修改文件通过
- `git diff --stat`：确认只改动指定位置
