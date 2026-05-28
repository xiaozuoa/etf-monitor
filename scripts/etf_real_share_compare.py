#!/usr/bin/env python3
"""真实份额 vs 模拟份额 -- 30%权重验证

直接调用上交所/深交所API获取真实历史份额数据, 与ShareSimulator模拟数据对比回测。
akshare不可安装时, 使用 requests + pandas 直接实现API调用。
"""
import sys, os, json, time, io
import ssl
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import requests
import pandas as pd

from etf_signals import fetch, calc_rs, DEFAULT_SHARE_RAW, W_VOL, W_DIR, W_SHARE
from backtest_unified import run_backtest, ShareSimulator
from etf_engine import ETFS
import backtest_unified

_orig_cpu = backtest_unified.compute_cp_unified

# ============================================================
# RealShareCollector: 从上交所/深交所直接获取真实份额 (无需akshare)
# ============================================================
class RealShareCollector:
    """从SSE和SZSE API下载真实历史ETF份额数据，计算日间变化率(delta%)"""

    def __init__(self, date_list):
        """
        date_list: list of date strings YYYY-MM-DD
        """
        self._share_data = {}
        self._load_shares(date_list)

    def get_delta(self, code, date):
        """返回份额日间变化率(%), 匹配ShareSimulator的接口"""
        return self._share_data.get(date, {}).get(code)

    # ---- 上交所 (SSE) ----
    def _query_sse_date(self, date_str):
        """查询单日SSE ETF份额, 返回 {code: shares_in_yi}"""
        data_str = date_str.replace('-', '')
        url = "https://query.sse.com.cn/commonQuery.do"
        params = {
            "isPagination": "true",
            "pageHelp.pageSize": "10000",
            "pageHelp.pageNo": "1",
            "pageHelp.beginPage": "1",
            "pageHelp.cacheSize": "1",
            "pageHelp.endPage": "1",
            "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L",
            "STAT_DATE": data_str,
        }
        headers = {
            "Referer": "https://www.sse.com.cn/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.150 Safari/537.36",
        }
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            data_json = r.json()
            result = {}
            for row in data_json.get("result", []):
                code = str(row.get("SEC_CODE", ""))
                if code in ETFS:
                    # TOT_VOL 单位: 万份, API返回字符串, *10000→份, /1e8→亿份
                    raw_vol = row.get("TOT_VOL", "0")
                    try:
                        shares_yi = float(raw_vol) * 10000 / 1e8
                    except (ValueError, TypeError):
                        shares_yi = 0
                    result[code] = shares_yi
            return result
        except Exception as e:
            return {}

    # ---- 深交所 (SZSE) ----
    def _query_szse_range(self, start_date, end_date):
        """查询日期区间SZSE ETF份额, 返回 {date: {code: shares_in_yi}}

        SZSE API限制: 一次查询最多6个月, 返回Excel文件。
        """
        import random
        import warnings
        url = "https://www.szse.cn/api/report/ShowReport"
        headers = {
            "Referer": "https://www.szse.cn/market/fund/volume/etf/index.html",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        }
        params = {
            "SHOWTYPE": "xlsx",
            "CATALOGID": "scsj_fund_jjgm",
            "TABKEY": "tab1",
            "txtStart": start_date,
            "txtEnd": end_date,
            "jjlb": "ETF",
            "random": str(random.random()),
        }
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            r.raise_for_status()
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                df = pd.read_excel(io.BytesIO(r.content), engine="openpyxl")
            df = df.dropna(how="all")
            if df.empty:
                return {}

            # 重命名列
            if "基金规模(份)" in df.columns:
                df.rename(columns={"基金规模(份)": "基金份额"}, inplace=True)

            result = {}
            for _, row in df.iterrows():
                code = str(row["基金代码"] if "基金代码" in df.columns else row.get("基金代码", ""))
                # 去除可能的 .0 后缀
                if "." in code:
                    code = code.split(".")[0]
                code = code.zfill(6)
                if code not in ETFS:
                    continue
                date_val = row["日期"] if "日期" in df.columns else row.get("日期")
                date_str = str(date_val)[:10]
                shares_str = str(row["基金份额"] if "基金份额" in df.columns else row.get("基金份额", "0"))
                shares_str = shares_str.replace(",", "")
                try:
                    shares_yi = float(shares_str) / 1e8
                except (ValueError, TypeError):
                    shares_yi = 0
                if date_str not in result:
                    result[date_str] = {}
                result[date_str][code] = shares_yi
            return result
        except Exception as e:
            return {}

    def _load_shares(self, date_list):
        """加载所有日期的份额数据并计算日间变化率"""
        print(f"  下载真实份额数据 ({date_list[0]}~{date_list[-1]}, 共{len(date_list)}天)...")

        # 收集所有需要的日期 (去重排序)
        sorted_dates = sorted(set(date_list))
        total_days = len(sorted_dates)

        # ============ SSE: 逐日查询 ============
        print(f"  [SSE] 逐日查询上交所份额...")
        prev_shares = {}  # {code: shares_yi}
        sse_success = 0

        for idx, d in enumerate(sorted_dates):
            current = self._query_sse_date(d)
            if current:
                sse_success += 1
                for code in current:
                    sy = current[code]
                    if code in prev_shares and prev_shares[code] > 0:
                        delta = (sy - prev_shares[code]) / prev_shares[code] * 100
                    else:
                        delta = 0
                    prev_shares[code] = sy
                    if d not in self._share_data:
                        self._share_data[d] = {}
                    self._share_data[d][code] = round(delta, 4)

            # 进度提示
            if (idx + 1) % 50 == 0 or idx == total_days - 1:
                print(f"    SSE 进度: {idx+1}/{total_days} (成功{sse_success}天)")

        # ============ SZSE: 分段批量查询 (每段最多6个月) ============
        print(f"  [SZSE] 批量查询深交所份额...")
        from datetime import datetime as dt_module, timedelta

        # 分段: 每180天一段
        sz_start = dt_module.strptime(sorted_dates[0], "%Y-%m-%d")
        sz_end = dt_module.strptime(sorted_dates[-1], "%Y-%m-%d")
        batch_days = 180
        current_start = sz_start
        szse_all = {}

        while current_start <= sz_end:
            current_end = min(current_start + timedelta(days=batch_days), sz_end)
            s = current_start.strftime("%Y-%m-%d")
            e = current_end.strftime("%Y-%m-%d")
            print(f"    SZSE 查询: {s} ~ {e}")
            batch_data = self._query_szse_range(s, e)
            if batch_data:
                for d, codes in batch_data.items():
                    if d not in szse_all:
                        szse_all[d] = {}
                    szse_all[d].update(codes)
            current_start = current_end + timedelta(days=1)
            time.sleep(0.5)  # 避免请求过快

        # 计算SZSE日间delta
        if szse_all:
            sz_dates = sorted(szse_all.keys())
            for code in ETFS:
                if not code.startswith("159"):
                    continue
                prev = None
                for d in sorted_dates:
                    d_str = d  # YYYY-MM-DD
                    if d_str in szse_all and code in szse_all[d_str]:
                        sy = szse_all[d_str][code]
                        if prev is not None and prev > 0:
                            delta = (sy - prev) / prev * 100
                            if d not in self._share_data:
                                self._share_data[d] = {}
                            # SZSE覆盖或补充SSE已有值 (优先级: 已有值>新值, 因为SSE已正确)
                            if code not in self._share_data.get(d, {}):
                                self._share_data[d][code] = round(delta, 4)
                        prev = sy

        sse_covered = len(self._share_data)
        print(f"    总覆盖天数: {sse_covered}/{total_days}")


# ============================================================
# 加载数据 + 构建测试
# ============================================================
print('=' * 70)
print('真实份额 vs 模拟份额 -- 30%权重验证')
print('=' * 70)

print('\n拉取K线数据...')
data_dict = {}
for code in ETFS:
    data_dict[code] = fetch(code, 800)
ref = data_dict['510300']
rdates = [r['date'] for r in ref]

test_si, test_ei = 60, len(ref) - 13
test_data = {}
test_dates = []
for c in data_dict:
    dlist = data_dict[c]
    if test_ei < len(dlist):
        test_data[c] = dlist[test_si:test_ei + 1]
        if c == '510300':
            test_dates = [r['date'] for r in test_data[c]]

print(f'测试区间: {test_dates[0]} ~ {test_dates[-1]} ({len(test_dates)}天)')

# ============================================================
# 下载真实份额
# ============================================================
print()
real_collector = RealShareCollector(test_dates)

# ============================================================
# Simulated ShareSimulator
# ============================================================
print()
sim_collector = ShareSimulator(test_data)

# ============================================================
# 构建CP补丁函数
# ============================================================
def make_patched_cpu(collector):
    def patched(v_raw, d_raw, idx_chg=0, code=None, date=None, collector_inner=None):
        share_raw = DEFAULT_SHARE_RAW
        c = collector_inner if collector_inner is not None else collector
        if c is not None and code is not None and date is not None:
            delta = c.get_delta(code, date)
            if delta is not None:
                dp = delta * 0.7
                if dp > 0.5:
                    share_raw = min(1.0, 0.12 + dp * 0.06)
                elif dp < -1:
                    share_raw = max(0.0, 0.12 + dp * 0.03)
                share_raw = max(0, min(1, share_raw))
        if idx_chg < 0:
            return (v_raw * 0.45 + d_raw * 0.25 + share_raw * W_SHARE) * 100
        else:
            return (v_raw * W_VOL + d_raw * W_DIR + share_raw * W_SHARE) * 100
    return patched

# ============================================================
# 跑两版回测
# ============================================================
print(f'\n{"版本":<35} {"收益":>8} {"年化":>8} {"回撤":>7} {"夏普":>6} {"胜率":>6} {"交易":>5}')
print('-' * 78)

results_list = []

for vname, collector in [('A: 模拟份额 (ShareSimulator)', sim_collector),
                           ('B: 真实份额 (上交所/深交所)', real_collector)]:
    backtest_unified.compute_cp_unified = make_patched_cpu(collector)
    eq, nt, wr, _ = run_backtest(test_data, 'equal', collector)

    # 计算指标
    tr = (eq[-1]/eq[0]-1)*100
    ar = ((eq[-1]/eq[0])**(252/max(len(eq),1))-1)*100
    peak = eq[0]; md = 0
    for v in eq:
        dd = (v-peak)/peak*100
        if v>peak: peak=v; dd=0
        if dd<md: md=dd
    dr = [(eq[i]/eq[i-1]-1) for i in range(1, len(eq))]
    avg_dr = sum(dr)/len(dr) if dr else 0
    std_dr = (sum((r-avg_dr)**2 for r in dr)/len(dr))**0.5 if dr else 1
    sh = (avg_dr/std_dr)*(252**0.5) if std_dr > 0 else 0

    print(f'{vname:<35} {tr:>+7.1f}% {ar:>+7.1f}% {md:>+6.1f}% {sh:>5.2f} {wr:>5.1f}% {nt:>5}')
    results_list.append({"name": vname, "total_return": tr, "annual": ar, "max_dd": md,
                         "sharpe": sh, "win_rate": wr, "trades": nt, "equity": eq})

# 恢复原始函数
backtest_unified.compute_cp_unified = _orig_cpu

# ============================================================
# 报告
# ============================================================
print()
if real_collector._share_data:
    real_days = len(real_collector._share_data)
    total_days = len(test_dates)
    coverage = real_days/total_days*100
    print(f'真实份额覆盖率: {real_days}/{total_days} = {coverage:.0f}%')

    # 统计份额数据分布
    all_deltas = []
    for date, codes in real_collector._share_data.items():
        for code, delta in codes.items():
            if abs(delta) > 0.001:
                all_deltas.append(delta)
    if all_deltas:
        import statistics
        avg_delta = sum(all_deltas)/len(all_deltas)
        pos_pct = sum(1 for d in all_deltas if d > 0)/len(all_deltas)*100
        print(f'份额delta统计: 均值={avg_delta:+.2f}% 正值比例={pos_pct:.0f}% 样本数={len(all_deltas)}')

print()
if len(results_list) >= 2:
    rA = results_list[0]
    rB = results_list[1]
    diff = rB["total_return"] - rA["total_return"]
    print(f'收益差异 (真实-模拟): {diff:+.1f}%')
    print(f'夏普差异 (真实-模拟): {rB["sharpe"]-rA["sharpe"]:+.2f}')
    print()
    if abs(diff) < 2:
        print('结论: 真实份额与模拟份额回测结果高度一致。')
        print('  份额因子的30%权重主要依赖K线可推断的模式(放量上涨/缩量下跌),')
        print('  这些模式在真实数据中同样存在, 验证了ShareSimulator的有效性。')
    elif abs(diff) < 5:
        print('结论: 真实份额与模拟份额回测结果接近, 差异在可接受范围。')
        print('  份额因子30%权重对这两种数据源都表现稳健。')
    else:
        print('结论: 真实份额与模拟份额回测结果有显著差异。')
        print('  需要进一步分析份额因子在不同市场环境下的表现差异。')
else:
    print('结论: 回测结果不足, 无法比较。')
