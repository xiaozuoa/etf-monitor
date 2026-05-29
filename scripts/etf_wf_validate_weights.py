#!/usr/bin/env python3
"""WF验证网格搜索TOP5 — 检查过拟合"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from etf_signals import fetch, calc_rs, DEFAULT_SHARE_RAW, W_SHARE
from backtest_unified import run_backtest, ShareSimulator
from etf_engine import ETFS
import backtest_unified

_orig_cpu = backtest_unified.compute_cp_unified

def make_patched_cpu(up_wd, dn_wd):
    up_wv = 0.80 - up_wd
    dn_wv = 0.80 - dn_wd
    def cpu(v_raw, d_raw, idx_chg=0, code=None, date=None, collector=None):
        share_raw = DEFAULT_SHARE_RAW
        c = collector
        if c is not None and code is not None and date is not None:
            delta = c.get_delta(code, date)
            if delta is not None:
                dp = delta
                if dp > 0.5: share_raw = min(1.0, 0.12 + dp * 0.06)
                elif dp < -1: share_raw = max(0.0, 0.12 + dp * 0.03)
                share_raw = max(0, min(1, share_raw))
        wv, wd = (dn_wv, dn_wd) if idx_chg < 0 else (up_wv, up_wd)
        return (v_raw * wv + d_raw * wd + share_raw * W_SHARE) * 100
    return cpu

print('=' * 70)
print('WF验证: TOP5组合 过拟合检查')
print('=' * 70)

print('拉取数据...')
data_dict = {}
for code in ETFS:
    data_dict[code] = fetch(code, 800)
ref = data_dict['510300']
rdates = [r['date'] for r in ref]
print(f'数据: {rdates[0]} ~ {rdates[-1]} ({len(ref)}条)')

TRAIN, TEST, STEP = 250, 250, 120

# TOP 5 + 2 baselines: (name, up_wd, dn_wd)
combos = [
    ('#1 0.35/0.20 (最优)', 0.35, 0.20),
    ('#2 0.35/0.25',       0.35, 0.25),
    ('#3 0.30/0.20',       0.30, 0.20),
    ('#4 0.30/0.25',       0.30, 0.25),
    ('#5 0.25/0.20',       0.25, 0.20),
    ('基准 0.20/0.25(旧)',  0.20, 0.25),
    ('基准 0.25/0.25',      0.25, 0.25),
]

results = {c[0]: [] for c in combos}

total_windows = 0
win_start = 60
while win_start + TRAIN + TEST < len(ref):
    test_si = win_start + TRAIN
    test_ei = min(test_si + TEST, len(ref) - 13)
    if test_ei <= test_si + 65: break

    # Build shared test_data and collector once per window
    test_data = {}
    for c in data_dict:
        dlist = data_dict[c]
        if test_ei < len(dlist):
            test_data[c] = dlist[test_si:test_ei + 1]
    if '510300' not in test_data or len(test_data['510300']) < 65:
        win_start += STEP; continue

    total_windows += 1
    wstart = test_data['510300'][0]['date']
    wend = test_data['510300'][-1]['date']
    collector = ShareSimulator(test_data)

    print(f'\n窗口 {total_windows}: {wstart} ~ {wend} ({len(test_data["510300"])}天)')
    print(f'  {"组合":<22} {"夏普":>6} {"收益":>8} {"交易":>5}')

    for name, up_wd, dn_wd in combos:
        backtest_unified.compute_cp_unified = make_patched_cpu(up_wd, dn_wd)
        eq, nt, wr, _ = run_backtest(test_data, 'equal', collector)
        if len(eq) < 2:
            results[name].append(None)
            print(f'  {name:<22} {"N/A":>6}')
            continue
        dr = [(eq[i]/eq[i-1]-1) for i in range(1, len(eq))]
        avg_dr = sum(dr)/len(dr) if dr else 0
        std_dr = (sum((r-avg_dr)**2 for r in dr)/len(dr))**0.5 if dr else 1
        sh = (avg_dr/std_dr)*(252**0.5) if std_dr > 0 else 0
        ret = (eq[-1]/eq[0]-1)*100
        results[name].append({'sharpe': round(sh, 2), 'return': round(ret, 1), 'trades': nt})
        print(f'  {name:<22} {sh:>6.2f} {ret:>+7.1f}% {nt:>5}')

    backtest_unified.compute_cp_unified = _orig_cpu
    win_start += STEP

print(f'\n{"="*70}')
print(f'完成 {total_windows} 个WF窗口')
print(f'\n{"组合":<22} {"WF均值Sharpe":>14} {"均值收益":>10} {"均值交易":>8} {"排名":>6}')
print('-' * 64)

# Average Sharpe per combo
avg_results = []
for name, _, _ in combos:
    valid = [r for r in results[name] if r is not None]
    if not valid: continue
    avg_sh = sum(r['sharpe'] for r in valid) / len(valid)
    avg_ret = sum(r['return'] for r in valid) / len(valid)
    avg_nt = sum(r['trades'] for r in valid) / len(valid)
    avg_results.append((name, avg_sh, avg_ret, avg_nt))

avg_results.sort(key=lambda x: x[1], reverse=True)

for rank, (name, avg_sh, avg_ret, avg_nt) in enumerate(avg_results, 1):
    marker = ' <<<' if rank == 1 else ''
    print(f'{name:<22} {avg_sh:>14.2f} {avg_ret:>+9.1f}% {avg_nt:>8.1f} {rank:>5}{marker}')

# Check if #1 (full backtest winner) is also #1 in WF
full_winner = '#1 0.35/0.20 (最优)'
wf_winner = avg_results[0][0]
print(f'\n全量最优: {full_winner}')
print(f'WF最优:   {wf_winner}')
if full_winner == wf_winner:
    print('结论: 不过拟合 ✓ — 全量最优=WF最优')
else:
    print(f'结论: 可能过拟合 ⚠ — 全量最优≠WF最优, 建议改用WF最优')
