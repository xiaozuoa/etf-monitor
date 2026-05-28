#!/usr/bin/env python3
"""真实份额权重消融 — 修正版: 方向权重恒定 (requests-based SSE/SZSE)"""
import sys, os, io, time
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import requests
import pandas as pd

from etf_signals import fetch, DEFAULT_SHARE_RAW
from backtest_unified import run_backtest
from etf_engine import ETFS
import backtest_unified

_orig_cpu = backtest_unified.compute_cp_unified

# ============================================================
# RealShareCollector (requests-based, same as original)
# ============================================================
class RealShareCollector:
    def __init__(self, date_list):
        self._share_data = {}
        self._load_shares(date_list)

    def get_delta(self, code, date):
        return self._share_data.get(date, {}).get(code)

    # ---- SSE API ----
    def _query_sse_date(self, date_str):
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
                    raw_vol = row.get("TOT_VOL", "0")
                    try:
                        shares_yi = float(raw_vol) * 10000 / 1e8
                    except (ValueError, TypeError):
                        shares_yi = 0
                    result[code] = shares_yi
            return result
        except Exception:
            return {}

    # ---- SZSE API ----
    def _query_szse_range(self, start_date, end_date):
        import random, warnings
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
            if "基金规模(份)" in df.columns:
                df.rename(columns={"基金规模(份)": "基金份额"}, inplace=True)
            result = {}
            for _, row in df.iterrows():
                code = str(row["基金代码"] if "基金代码" in df.columns else row.get("基金代码", ""))
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
        except Exception:
            return {}

    def _load_shares(self, date_list):
        print(f"  下载真实份额数据 ({date_list[0]}~{date_list[-1]}, 共{len(date_list)}天)...")
        sorted_dates = sorted(set(date_list))
        total_days = len(sorted_dates)

        # SSE: 逐日查询
        print(f"  [SSE] 逐日查询上交所份额...")
        prev_shares = {}
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
            if (idx + 1) % 50 == 0 or idx == total_days - 1:
                print(f"    SSE 进度: {idx+1}/{total_days} (成功{sse_success}天)")

        # SZSE: 分段批量查询
        print(f"  [SZSE] 批量查询深交所份额...")
        from datetime import datetime as dt_module, timedelta
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
            time.sleep(0.5)

        # 计算SZSE日间delta
        if szse_all:
            sz_dates = sorted(szse_all.keys())
            for code in ETFS:
                if not code.startswith("159"):
                    continue
                prev = None
                for d in sorted_dates:
                    if d in szse_all and code in szse_all[d]:
                        sy = szse_all[d][code]
                        if prev is not None and prev > 0:
                            delta = (sy - prev) / prev * 100
                            if d not in self._share_data:
                                self._share_data[d] = {}
                            if code not in self._share_data.get(d, {}):
                                self._share_data[d][code] = round(delta, 4)
                        prev = sy

        print(f"    总覆盖天数: {len(self._share_data)}/{total_days}")


# ============================================================
# 构建补丁函数 — 修正版: 方向权重恒定
# ============================================================
def make_patched_cpu(ws_up, wd_up, ws_dn, wd_dn):
    """方向权重恒定，只 trade off vol vs share"""
    def patched(v_raw, d_raw, idx_chg=0, code=None, date=None, collector=None):
        share_raw = DEFAULT_SHARE_RAW
        c = collector
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
            wv = 1.0 - wd_dn - ws_dn
            return (v_raw * wv + d_raw * wd_dn + share_raw * ws_dn) * 100
        else:
            wv = 1.0 - wd_up - ws_up
            return (v_raw * wv + d_raw * wd_up + share_raw * ws_up) * 100
    return patched


print('=' * 70)
print('真实份额权重消融 (修正版: 方向权重恒定)')
print('=' * 70)

print('\n拉取K线...')
data_dict = {}
for code in ETFS:
    data_dict[code] = fetch(code, 800)
ref = data_dict['510300']

test_si, test_ei = 60, len(ref) - 13
test_data = {}
test_dates = []
for c in data_dict:
    dlist = data_dict[c]
    if test_ei < len(dlist):
        test_data[c] = dlist[test_si:test_ei + 1]
        if c == '510300':
            test_dates = [r['date'] for r in test_data[c]]

print(f'测试: {test_dates[0]} ~ {test_dates[-1]}')

print()
real_collector = RealShareCollector(test_dates)

# 方向权重恒定: 涨市0.20, 跌市0.25 (当前生产值)
# 份额权重: 0% 10% 20% 30% 40% 50%
versions = {
    '0%份额':  (0.00, 0.20, 0.00, 0.25),
    '10%份额': (0.10, 0.20, 0.10, 0.25),
    '20%份额': (0.20, 0.20, 0.20, 0.25),
    '30%份额': (0.30, 0.20, 0.30, 0.25),
    '40%份额': (0.40, 0.20, 0.40, 0.25),
    '50%份额': (0.50, 0.20, 0.50, 0.25),
}

print(f'\n{"版本":<14} {"收益":>8} {"年化":>8} {"回撤":>7} {"夏普":>6} {"胜率":>6} {"交易":>5}')
print('-' * 58)

results = {}
for vname, (ws_up, wd_up, ws_dn, wd_dn) in versions.items():
    backtest_unified.compute_cp_unified = make_patched_cpu(ws_up, wd_up, ws_dn, wd_dn)
    eq, nt, wr, _ = run_backtest(test_data, 'equal', real_collector)

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

    results[vname] = {'ret': tr, 'ar': ar, 'dd': md, 'sh': sh, 'wr': wr, 'nt': nt}
    print(f'{vname:<14} {tr:>+7.1f}% {ar:>+7.1f}% {md:>+6.1f}% {sh:>5.2f} {wr:>5.1f}% {nt:>5}')

backtest_unified.compute_cp_unified = _orig_cpu

print(f'\n=== 综合排名 (Sharpe×2 + 收益/100 - |回撤|/50) ===')
scores = {v: r['sh']*2 + r['ret']/100 - abs(r['dd'])/50 for v, r in results.items()}
best = max(scores, key=scores.get)
for vname in sorted(scores, key=scores.get, reverse=True):
    m = ' <<<' if vname == best else ''
    print(f'  {vname:<14} {scores[vname]:.3f}{m}')

print(f'\n结论: 最优 = {best}')
print(f'当前生产用 30% — ', end='')
if best == '30%份额':
    print('正确 ✓')
else:
    print(f'应改为 {best}')
