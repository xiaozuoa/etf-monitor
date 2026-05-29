#!/usr/bin/env python3
"""权重网格搜索 — W_SHARE=0.20固定，找最优W_DIR/W_VOL"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from etf_signals import fetch, calc_rs, DEFAULT_SHARE_RAW, W_SHARE
from backtest_unified import run_backtest, ShareSimulator
from etf_engine import ETFS
import etf_signals, backtest_unified

_orig_cp = etf_signals.compute_cp
_orig_cpu = backtest_unified.compute_cp_unified

def make_patched(up_wd, dn_wd):
    up_wv = 0.80 - up_wd  # W_SHARE=0.20 fixed
    dn_wv = 0.80 - dn_wd
    def cp(records, day_i, idx_chg, share_raw=None):
        if share_raw is None: share_raw = DEFAULT_SHARE_RAW
        r = records[day_i]
        chg = (r['c'] - records[day_i - 1]['c']) / records[day_i - 1]['c'] * 100
        vols = [records[j]['v'] for j in range(max(0, day_i - 20), day_i)]
        ma20 = sum(vols) / len(vols) if vols else 1
        vr = r['v'] / ma20 if ma20 > 0 else 1
        v_raw = min(1, max(0, (vr - 0.7) / 1.3)) if vr >= 0.7 else 0
        rs, is_c = calc_rs(chg, idx_chg, vr)
        d_raw = rs / 100
        wv, wd = (dn_wv, dn_wd) if idx_chg < 0 else (up_wv, up_wd)
        return (v_raw * wv + d_raw * wd + share_raw * W_SHARE) * 100, chg, vr, is_c, r['c']
    return cp

def make_patched_cpu(up_wd, dn_wd):
    up_wv = 0.80 - up_wd
    dn_wv = 0.80 - dn_wd
    def cpu(v_raw, d_raw, idx_chg=0, code=None, date=None, collector=None):
        share_raw = DEFAULT_SHARE_RAW
        c = collector
        if c is not None and code is not None and date is not None:
            delta = c.get_delta(code, date)
            if delta is not None:
                dp = delta  # aligned with fix #1
                if dp > 0.5: share_raw = min(1.0, 0.12 + dp * 0.06)
                elif dp < -1: share_raw = max(0.0, 0.12 + dp * 0.03)
                share_raw = max(0, min(1, share_raw))
        wv, wd = (dn_wv, dn_wd) if idx_chg < 0 else (up_wv, up_wd)
        return (v_raw * wv + d_raw * wd + share_raw * W_SHARE) * 100
    return cpu

print('=' * 70)
print('权重网格搜索 (W_SHARE=0.20固定)')
print('=' * 70)

print('\n拉取数据...')
data_dict = {}
for code in ETFS:
    data_dict[code] = fetch(code, 800)
ref = data_dict['510300']

test_si, test_ei = 60, len(ref) - 13
test_data = {}
for c in data_dict:
    dlist = data_dict[c]
    if test_ei < len(dlist):
        test_data[c] = dlist[test_si:test_ei + 1]

up_wds = [0.15, 0.20, 0.25, 0.30, 0.35]
dn_wds = [0.20, 0.25, 0.30, 0.35, 0.40]

print(f'组合数: {len(up_wds)}x{len(dn_wds)}={len(up_wds)*len(dn_wds)}')
print(f'\n{"涨WD":<6} {"跌WD":<6} {"收益":>8} {"回撤":>7} {"夏普":>6} {"交易":>5} {"综合分":>8}')
print('-' * 54)

best_score = -999
best_params = None
all_results = []

for up_wd in up_wds:
    for dn_wd in dn_wds:
        up_wv = 0.80 - up_wd
        dn_wv = 0.80 - dn_wd

        etf_signals.compute_cp = make_patched(up_wd, dn_wd)
        backtest_unified.compute_cp_unified = make_patched_cpu(up_wd, dn_wd)
        collector = ShareSimulator(test_data)
        eq, nt, wr, _ = run_backtest(test_data, 'equal', collector)

        tr = (eq[-1]/eq[0]-1)*100
        peak = eq[0]; md = 0
        for v in eq:
            dd = (v-peak)/peak*100
            if v>peak: peak=v; dd=0
            if dd<md: md=dd
        dr = [(eq[i]/eq[i-1]-1) for i in range(1, len(eq))]
        avg_dr = sum(dr)/len(dr) if dr else 0
        std_dr = (sum((r-avg_dr)**2 for r in dr)/len(dr))**0.5 if dr else 1
        sh = (avg_dr/std_dr)*(252**0.5) if std_dr > 0 else 0

        score = sh * 2 + tr / 100 - abs(md) / 50
        all_results.append((up_wd, dn_wd, up_wv, dn_wv, tr, md, sh, nt, score))

        if score > best_score:
            best_score = score
            best_params = (up_wd, dn_wd, up_wv, dn_wv, tr, md, sh, nt)

etf_signals.compute_cp = _orig_cp
backtest_unified.compute_cp_unified = _orig_cpu

# Show top 10
all_results.sort(key=lambda x: x[8], reverse=True)
print('\n=== TOP 10 ===')
print(f'{"涨WD":<6} {"涨WV":<6} {"跌WD":<6} {"跌WV":<6} {"收益":>8} {"回撤":>7} {"夏普":>6} {"综合分":>8}')
print('-' * 58)
for r in all_results[:10]:
    m = ' <<<' if r[8] >= best_score else ''
    print(f'{r[0]:<6.2f} {r[2]:<6.2f} {r[1]:<6.2f} {r[3]:<6.2f} {r[4]:>+7.1f}% {r[5]:>+6.1f}% {r[6]:>5.2f} {r[8]:>8.3f}{m}')

print(f'\n最优: 涨W_DIR={best_params[0]:.2f} 涨W_VOL={best_params[2]:.2f}  跌W_DIR={best_params[1]:.2f} 跌W_VOL={best_params[3]:.2f}')
print(f'收益={best_params[4]:.1f}% 回撤={best_params[5]:.1f}% 夏普={best_params[6]:.2f}')
