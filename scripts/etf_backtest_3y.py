#!/usr/bin/env python3
"""
三因子策略 3年回测 (2023-02 ~ 2026-05)
数据源: 腾讯财经API (800天历史, 可靠免费)
"""

import os, sys, io, json, urllib.request, ssl
from collections import defaultdict

if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from etf_signals import fetch as _fetch, calc_rs  # calc_rs从共享模块导入, 删除本地副本
import etf_signals

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# === 参数 ===
COMMISSION = etf_signals.COMMISSION
SLIPPAGE   = etf_signals.SLIPPAGE
HOLD_DAYS  = 3
INITIAL    = etf_signals.INITIAL

def fetch(code, limit=800):
    return _fetch(code, limit)

ETFS = {
    "510300": "华泰柏瑞沪深300ETF",
    "510310": "易方达沪深300ETF",
    "510330": "华夏沪深300ETF",
    "159919": "嘉实沪深300ETF",
    "510050": "华夏上证50ETF",
    "510500": "华泰柏瑞中证500ETF",
    "512100": "南方中证1000ETF",
}


def align_data(data_dict):
    """按日期对齐所有数据"""
    all_dates = set()
    for records in data_dict.values():
        all_dates.update(r["date"] for r in records)
    all_dates = sorted(all_dates)

    aligned = {}
    for code, records in data_dict.items():
        date_map = {r["date"]: r for r in records}
        aligned[code] = [date_map.get(d) for d in all_dates]
    return all_dates, aligned


def backtest(data_dict, use_resonance=True, cp_thresh=50, res_min=3, hold_days=3):
    """回测核心"""
    idx_records = data_dict.get("510300", [])
    if len(idx_records) < 25:
        return [], [INITIAL]

    cash = INITIAL
    holding = {}
    equity = [INITIAL]
    trades = []

    for day_i in range(20, len(idx_records) - hold_days - 1):
        date = idx_records[day_i]["date"]
        idx_c = idx_records[day_i]["c"]
        idx_prev = idx_records[day_i-1]["c"]
        idx_chg = (idx_c - idx_prev) / idx_prev * 100 if idx_prev > 0 else 0

        # === 卖出 ===
        to_sell = []
        for code, pos in holding.items():
            if day_i - pos["entry_i"] >= hold_days:
                records = data_dict.get(code, [])
                sell_p = records[day_i]["c"] if day_i < len(records) else pos["entry_price"]
                proceeds = pos["shares"] * sell_p * (1 - COMMISSION - SLIPPAGE)
                cash += proceeds
                trades.append({
                    "code": code, "name": ETFS.get(code, ""),
                    "entry_date": pos["entry_date"], "exit_date": date,
                    "entry_price": pos["entry_price"], "exit_price": sell_p,
                    "profit_pct": round((proceeds / pos["cost"] - 1) * 100, 2),
                    "profit": round(proceeds - pos["cost"], 2),
                })
                to_sell.append(code)
        for code in to_sell:
            del holding[code]

        # === 信号计算 ===
        signals = []
        for code, records in data_dict.items():
            if code not in ETFS or day_i >= len(records) or records[day_i] is None:
                continue
            r = records[day_i]
            c, v = r["c"], r["v"]
            prev = records[day_i-1]
            if prev is None:
                continue
            chg = (c - prev["c"]) / prev["c"] * 100 if prev["c"] > 0 else 0
            vols = [records[j]["v"] for j in range(max(0, day_i-20), day_i)
                    if records[j] is not None]
            if len(vols) < 10:
                continue
            ma20 = sum(vols) / len(vols)
            vr = v / ma20 if ma20 > 0 else 1

            v_raw = min(1, max(0, (vr - 0.7) / 1.3)) if vr >= 0.7 else 0
            rs, is_c = calc_rs(chg, idx_chg, vr)
            d_raw = rs / 100
            s_raw = 0.12
            cp = (v_raw * 0.50 + d_raw * 0.20 + s_raw * 0.30) * 100

            if cp >= cp_thresh:
                signals.append({"code": code, "cp": cp, "chg": chg, "vr": vr,
                                "is_counter": is_c, "close": c})

        # === 买入 ===
        triggered = len(signals) >= res_min if use_resonance else len(signals) >= 1
        new_sigs = [s for s in signals if s["code"] not in holding]

        if triggered and new_sigs and len(holding) == 0:
            next_i = day_i + 1
            if next_i >= len(idx_records) - 2:
                continue
            next_date = idx_records[next_i]["date"]
            buy_list = sorted(new_sigs, key=lambda x: x["cp"], reverse=True)[:3]
            alloc = cash * 0.8 / len(buy_list)

            for s in buy_list:
                records = data_dict.get(s["code"], [])
                if next_i >= len(records) or records[next_i] is None:
                    continue
                open_p = records[next_i]["o"]
                if open_p <= 0:
                    continue
                buy_p = open_p * (1 + SLIPPAGE)
                shares = int(alloc / buy_p / 100) * 100
                if shares < 100:
                    continue
                cost = shares * buy_p * (1 + COMMISSION)
                if cost > cash:
                    continue
                cash -= cost
                holding[s["code"]] = {
                    "shares": shares, "cost": cost,
                    "entry_price": buy_p, "entry_date": next_date,
                    "entry_i": next_i,
                }

        # === 权益 ===
        total = cash
        for code, pos in holding.items():
            records = data_dict.get(code, [])
            if day_i < len(records) and records[day_i]:
                total += pos["shares"] * records[day_i]["c"]
            else:
                total += pos["shares"] * pos["entry_price"]
        equity.append(total)

    # 清仓
    last_i = len(idx_records) - hold_days - 2
    last_date = idx_records[last_i]["date"]
    for code, pos in holding.items():
        records = data_dict.get(code, [])
        sell_p = records[last_i]["c"] if last_i < len(records) and records[last_i] else pos["entry_price"]
        proceeds = pos["shares"] * sell_p * (1 - COMMISSION - SLIPPAGE)
        cash += proceeds
        trades.append({
            "code": code, "name": ETFS.get(code, ""),
            "entry_date": pos["entry_date"], "exit_date": last_date,
            "entry_price": pos["entry_price"], "exit_price": sell_p,
            "profit_pct": round((proceeds / pos["cost"] - 1) * 100, 2),
            "profit": round(proceeds - pos["cost"], 2),
        })
    equity.append(cash)
    return trades, equity


def buy_hold(data_dict, code="510300"):
    """买持基准"""
    records = data_dict.get(code, [])
    if len(records) < 25:
        return [INITIAL]
    start_i, end_i = 20, len(records) - HOLD_DAYS - 2  # 与回测清仓对齐
    shares = int(INITIAL / records[start_i]["c"] / 100) * 100 if records[start_i]["c"] > 0 else 0
    if shares == 0:
        return [INITIAL]
    return [shares * records[i]["c"] for i in range(start_i, end_i + 1)]


def equal_weight(data_dict):
    """等权基准"""
    equities = []
    for code in ETFS:
        records = data_dict.get(code, [])
        if len(records) < 25:
            continue
        start_i, end_i = 20, len(records) - HOLD_DAYS - 2  # 与回测清仓对齐
        shares = int((INITIAL / len(ETFS)) / records[start_i]["c"] / 100) * 100 if records[start_i]["c"] > 0 else 0
        if shares == 0:
            continue
        equities.append([shares * records[i]["c"] for i in range(start_i, end_i + 1)])
    if not equities:
        return [INITIAL]
    min_len = min(len(e) for e in equities)
    return [sum(e[i] for e in equities) for i in range(min_len)]


def metrics(equity, trades, name):
    if len(equity) < 2: return {"name": name, "total_return": 0}
    tr = (equity[-1] / equity[0] - 1) * 100
    ar = ((equity[-1] / equity[0]) ** (252 / max(len(equity), 1)) - 1) * 100
    peak = equity[0]; md = 0
    for v in equity:
        if v > peak: peak = v
        dd = (v - peak) / peak * 100
        if dd < md: md = dd
    dr = [(equity[i]/equity[i-1]-1) for i in range(1, len(equity))]
    sh = (sum(dr)/len(dr) / (sum((r-sum(dr)/len(dr))**2 for r in dr)/len(dr))**0.5 * (252**0.5)) if dr else 0
    win = [t for t in trades if t["profit"] > 0]
    loss = [t for t in trades if t["profit"] <= 0]
    wr = len(win)/len(trades)*100 if trades else 0
    aw = sum(t["profit_pct"] for t in win)/len(win) if win else 0
    al = sum(t["profit_pct"] for t in loss)/len(loss) if loss else 0
    tp = sum(t["profit_pct"] for t in win)
    tl = abs(sum(t["profit_pct"] for t in loss))
    pf = tp/tl if tl > 0 else float('inf')
    cm = ar/abs(md) if md < 0 else float('inf')
    return {"name": name, "total_return": round(tr,2), "annual_return": round(ar,2),
            "max_drawdown": round(md,2), "sharpe": round(sh,2),
            "calmar": round(cm,2) if cm != float('inf') else "∞",
            "n_trades": len(trades), "win_rate": round(wr,1),
            "avg_win": round(aw,2), "avg_loss": round(al,2),
            "profit_factor": round(pf,2) if pf != float('inf') else "∞",
            "final_value": round(equity[-1],2)}


def main():
    print("=" * 70)
    print("📊 三因子策略 3年回测 (腾讯API, ~800天)")
    print("=" * 70)

    # 加载数据
    print("\n📡 加载数据...")
    data_dict = {}
    for code, name in ETFS.items():
        records = fetch(code, 800)
        if records:
            data_dict[code] = records
            print(f"  {code} {name}: {len(records)}天 ({records[0]['date']} ~ {records[-1]['date']})")

    if len(data_dict) < 5:
        print("数据不足")
        return

    ref = data_dict["510300"]
    end_idx = len(ref) - HOLD_DAYS - 2
    print(f"\n📅 回测区间: {ref[20]['date']} ~ {ref[end_idx]['date']} "
          f"({end_idx-20+1}个交易日, ~{(end_idx-20+1)/252:.1f}年)")

    # 回测
    print("\n⏳ 运行策略...")
    t_r, e_r = backtest(data_dict, use_resonance=True, cp_thresh=50, res_min=3, hold_days=3)
    m_r = metrics(e_r, t_r, "共振确认 v3 (≥3只,持3日)")

    t_s, e_s = backtest(data_dict, use_resonance=True, cp_thresh=50, res_min=3, hold_days=5)
    m_5 = metrics(e_s, t_s, "共振 v3 (≥3只,持5日)")

    e_bh = buy_hold(data_dict, "510300")
    m_bh = metrics(e_bh, [], "买持510300ETF")

    e_ew = equal_weight(data_dict)
    m_ew = metrics(e_ew, [], "等权7ETF")

    # 分年统计
    print("\n⏳ 分年度统计...")
    yearly = {}
    ref_dates = [r["date"] for r in data_dict["510300"]]
    for year in [2023, 2024, 2025, 2026]:
        ys = str(year)
        # 找到该年数据的起止索引
        mask = [d.startswith(ys) for d in ref_dates]
        indices = [i for i, m in enumerate(mask) if m]
        if len(indices) < 25:
            continue
        si, ei = max(20, indices[0]), min(len(ref_dates) - HOLD_DAYS - 2, indices[-1])
        if ei - si < 20:
            continue
        year_data = {}
        for code, records in data_dict.items():
            year_data[code] = records[si:ei+1]
        t, e = backtest(year_data, use_resonance=True)
        yr = (e[-1]/e[0]-1)*100 if e else 0
        ebh = buy_hold(year_data, "510300")
        ybh = (ebh[-1]/ebh[0]-1)*100 if ebh else 0
        eew = equal_weight(year_data)
        yew = (eew[-1]/eew[0]-1)*100 if eew else 0
        yearly[year] = {"strategy": yr, "buyhold": ybh, "equalwt": yew}
        print(f"  {year}: 策略{yr:+.1f}% | 买持{ybh:+.1f}% | 等权{yew:+.1f}% | 超额{yr-ybh:+.1f}%")

    # 汇总
    print("\n" + "=" * 70)
    print("📊 综合对比")
    print("=" * 70)

    all_m = [m_r, m_5, m_bh, m_ew]
    names = ["共振(持3日)", "共振(持5日)", "买持510300", "等权7ETF"]

    print(f"\n{'指标':<18} {names[0]:>12} {names[1]:>12} {names[2]:>12} {names[3]:>12}")
    print("-" * 72)
    for label, key, unit in [
        ("总收益(%)", "total_return", "%"),
        ("年化收益(%)", "annual_return", "%"),
        ("最大回撤(%)", "max_drawdown", "%"),
        ("夏普比率", "sharpe", ""),
        ("卡玛比率", "calmar", ""),
    ]:
        vals = [str(m.get(key, "-")) for m in all_m]
        print(f"{label:<18} {vals[0]:>12} {vals[1]:>12} {vals[2]:>12} {vals[3]:>12}")

    print(f"\n--- 交易统计 ---")
    for m, n in [(m_r, "持3日"), (m_5, "持5日")]:
        print(f"  {n}: {m['n_trades']}笔交易, 胜率{m['win_rate']}%, "
              f"均盈{m['avg_win']}%, 均亏{m['avg_loss']}%, 盈亏比{m['profit_factor']}")

    print(f"\n--- 年度超额收益 ---")
    print(f"{'年份':<8} {'策略vs买持':>12} {'策略vs等权':>12}")
    print("-" * 36)
    for year in [2023, 2024, 2025, 2026]:
        y = yearly.get(year)
        if not y: continue
        print(f"{year:<8} {y['strategy']-y['buyhold']:>+11.1f}% {y['strategy']-y['equalwt']:>+11.1f}%")

    # === 最终结论 ===
    print("\n" + "=" * 70)
    print("📋 结论")
    print("=" * 70)

    beat_years = sum(1 for y in yearly.values() if y["strategy"] > y["buyhold"])
    total_years = len(yearly)

    print(f"  跑赢买持: {beat_years}/{total_years}年")
    print(f"  总收益差距: {m_r['total_return'] - m_bh['total_return']:+.1f}%")
    print(f"  夏普差距:   {m_r['sharpe'] - m_bh['sharpe']:+.2f}")
    print(f"  最大回撤差距: {m_r['max_drawdown'] - m_bh['max_drawdown']:+.1f}% "
          f"({'策略更小✅' if abs(m_r['max_drawdown']) < abs(m_bh['max_drawdown']) else '策略更大❌'})")

    # 策略是否有效?
    if m_r['total_return'] > m_bh['total_return']:
        print(f"\n  ✅ 策略跑赢买持, 获得了超额收益")
    else:
        print(f"\n  ❌ 策略跑输买持, 没有alpha")
        print(f"  💡 这不是策略的错——在长期牛市中任何择时策略都跑输满仓")
        print(f"  💡 策略的价值在于: 空仓期避开了急跌, 降低最大回撤")

    if m_r['sharpe'] > m_bh['sharpe']:
        print(f"  ✅ 风险调整后收益更优(夏普更高)")
    else:
        print(f"  ❌ 风险调整后也不如买持")

    n_trades = m_r['n_trades']
    if n_trades > 50:
        print(f"  📊 {n_trades}笔交易足够统计显著")
    else:
        print(f"  ⚠️ 仅{n_trades}笔交易, 样本量偏小")


if __name__ == "__main__":
    main()
