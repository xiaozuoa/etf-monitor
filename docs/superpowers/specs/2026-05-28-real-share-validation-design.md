# Design: 真实份额数据灌入回测

## 方法
新建 RealShareCollector 替换 ShareSimulator。
用 akshare 批量下载历史份额，计算真实 delta_pct。
两个版本对比同一回测。

## RealShareCollector
- 构造函数: 接收 ETF 列表 + 日期范围，调 akshare 批量下载
- get_delta(code, date): 返回真实 delta_pct
- 接口与 ShareSimulator 一致，可直接替换

## 验证
- A: ShareSimulator (模拟份额) vs B: RealShareCollector (真实份额)
- 对比 3 年全量回测的收益/夏普/回撤
- 如果 B > A: 真实份额因子比模拟的更有效
- 如果 B < A: 30% 权重可能是浪费
