#!/usr/bin/env python3
"""份额因子消融实验 -- 3版本A/B对比"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from etf_signals import fetch, calc_rs, DEFAULT_SHARE_RAW
from backtest_unified import run_backtest, ShareSimulator
from etf_engine import ETFS
import etf_signals, backtest_unified

_orig_cp = etf_signals.compute_cp
_orig_cpu = backtest_unified.compute_cp_unified

def make_patched(up_v, up_d, up_s, dn_v, dn_d, dn_s):
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
        wv, wd, ws = (dn_v, dn_d, dn_s) if idx_chg < 0 else (up_v, up_d, up_s)
        return (v_raw * wv + d_raw * wd + share_raw * ws) * 100, chg, vr, is_c, r['c']
    return cp

def make_patched_cpu(up_v, up_d, up_s, dn_v, dn_d, dn_s):
    def cpu(v_raw, d_raw, idx_chg=0, code=None, date=None, collector=None):
        share_raw = DEFAULT_SHARE_RAW
        if collector is not None and code is not None and date is not None:
            delta = collector.get_delta(code, date)
            if delta is not None:
                dp = delta*0.7
                if dp>0.5: share_raw = min(1.0, 0.12+dp*0.06)
                elif dp<-1: share_raw = max(0.0, 0.12+dp*0.03)
                share_raw = max(0,min(1,share_raw))
        wv, wd, ws = (dn_v, dn_d, dn_s) if idx_chg < 0 else (up_v, up_d, up_s)
        return (v_raw*wv + d_raw*wd + share_raw*ws)*100
    return cpu

print('=' * 70)
print('份额因子消融实验')
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
print(f'测试: {test_data["510300"][0]["date"]} ~ {test_data["510300"][-1]["date"]}')

versions = {
    'A: 当前 (30%份额)':   (0.50, 0.20, 0.30, 0.45, 0.25, 0.30),
    'B: 去份额 (0%)':      (0.70, 0.30, 0.00, 0.65, 0.35, 0.00),
    'C: 份额翻倍 (50%)':   (0.35, 0.15, 0.50, 0.30, 0.20, 0.50),
}

print(f'\n{"版本":<25} {"收益":>8} {"年化":>8} {"回撤":>7} {"夏普":>6} {"胜率":>6} {"交易":>5}')
print('-' * 68)

results = {}
for vname, w in versions.items():
    etf_signals.compute_cp = make_patched(*w)
    backtest_unified.compute_cp_unified = make_patched_cpu(*w)
    collector = ShareSimulator(test_data)
    eq, nt, wr, _ = run_backtest(test_data, 'equal', collector)

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
    print(f'{vname:<25} {tr:>+7.1f}% {ar:>+7.1f}% {md:>+6.1f}% {sh:>5.2f} {wr:>5.1f}% {nt:>5}')

etf_signals.compute_cp = _orig_cp
backtest_unified.compute_cp_unified = _orig_cpu

print(f'\n=== 综合排名 (Sharpe x2 + 收益/100 - |回撤|/50) ===')
scores = {v: r['sh']*2 + r['ret']/100 - abs(r['dd'])/50 for v, r in results.items()}
best = max(scores, key=scores.get)
for vname in sorted(scores, key=scores.get, reverse=True):
    m = ' <<<' if vname == best else ''
    print(f'  {vname:<25} {scores[vname]:.3f}{m}')

print(f'\n结论: {best}')
