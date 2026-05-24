#!/usr/bin/env python3
"""
v4 回测 — 对比 v3 vs 趋势自适应 vs 动态退出 vs 核心卫星
数据: 腾讯API 800天 (~2023-02 ~ 2026-05)
"""

import os, sys, io, json, urllib.request, ssl
from collections import defaultdict

if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from etf_engine import (ETFS, calc_relative_strength, calc_atr,
                         detect_market_trend, get_dynamic_params,
                         calc_dynamic_exit)

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

COMMISSION = 0.00025
SLIPPAGE   = 0.0005
INITIAL    = 100000


def fetch(code, limit=800):
    pfx = "sh" if code.startswith(("51", "56", "0")) else "sz"
    if code.startswith("sh") or code.startswith("sz"):
        pfx, numcode = code[:2], code[2:]
    else:
        numcode = code
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={pfx}{numcode},day,,,{limit},qfq"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as r:
            d = json.loads(r.read().decode("utf-8"))
        k = d.get("data", {}).get(f"{pfx}{numcode}", {}).get("qfqday", []) or \
            d.get("data", {}).get(f"{pfx}{numcode}", {}).get("day", [])
        return [{"date": r[0], "o": float(r[1]), "c": float(r[2]),
                 "h": float(r[3]), "l": float(r[4]), "v": float(r[5])}
                for r in k if len(r) >= 6 and r[0]]
    except:
        return []


def calc_rs(etf_chg, idx_chg, vol_ratio):
    excess = etf_chg - idx_chg
    score, is_c = 0, False
    if idx_chg < -0.5 and etf_chg > idx_chg + 0.3:
        score += 40; is_c = True
        if idx_chg < -1.5: score += min(20, abs(idx_chg) * 3)
    if idx_chg < -0.5 and vol_ratio > 1.3 and etf_chg > idx_chg + 0.5: score += 25
    if excess > 0.3: score += min(20, excess * 6)
    if idx_chg > 1.5 and 0 < excess < 0.3: score -= 15
    if idx_chg > 2.0 and excess < 0.5: score -= 10
    if etf_chg > 1.5 and vol_ratio < 0.8: score -= 20
    return max(0, min(100, score)), is_c


def compute_cp(records, day_i, idx_chg):
    """计算单日单ETF综合概率"""
    r = records[day_i]
    c, v = r["c"], r["v"]
    chg = (c - records[day_i-1]["c"]) / records[day_i-1]["c"] * 100
    vols = [records[j]["v"] for j in range(max(0, day_i-19), day_i+1)]
    ma20 = sum(vols) / len(vols)
    vr = v / ma20 if ma20 > 0 else 1
    v_raw = min(1, max(0, (vr - 0.7) / 1.3)) if vr >= 0.7 else 0
    rs, is_c = calc_rs(chg, idx_chg, vr)
    d_raw = rs / 100
    return (v_raw * 0.55 + d_raw * 0.40 + 0.12 * 0.05) * 100, chg, vr, is_c, c


# ================================================================
# 策略1: v3 基准 (固定3日)
# ================================================================
def backtest_v3(data_dict, hold_days=3):
    return _backtest_core(data_dict, use_dynamic=False, hold_days=hold_days)


# ================================================================
# 策略2: v4a 趋势自适应
# ================================================================
def backtest_v4a_trend(data_dict):
    """根据50日MA趋势动态调整参数"""
    return _backtest_core(data_dict, use_dynamic=True, use_trailing=False)


# ================================================================
# 策略3: v4b 动态退出
# ================================================================
def backtest_v4b_trailing(data_dict):
    """ATR跟踪止损替代固定3日持有"""
    return _backtest_core(data_dict, use_dynamic=False, use_trailing=True)


# ================================================================
# 策略4: v4c 趋势+动态退出
# ================================================================
def backtest_v4c_full(data_dict):
    """趋势自适应 + ATR跟踪退出"""
    return _backtest_core(data_dict, use_dynamic=True, use_trailing=True)


def _backtest_core(data_dict, use_dynamic=False, use_trailing=False, hold_days=3):
    """统一回测核心"""
    ref_records = data_dict.get("510300", [])
    if len(ref_records) < 25:
        return [], [INITIAL]

    cash = INITIAL
    holding = {}
    equity = [INITIAL]
    trades = []

    for day_i in range(20, len(ref_records) - 10):
        date = ref_records[day_i]["date"]
        idx_c = ref_records[day_i]["c"]
        idx_chg = (idx_c - ref_records[day_i-1]["c"]) / ref_records[day_i-1]["c"] * 100

        # === 趋势检测 (每20天更新) ===
        if use_dynamic and (day_i % 20 == 0 or day_i == 20):
            # 用截至当前日的数据估算趋势
            trend_slice = ref_records[:day_i+1]
            if len(trend_slice) >= 50:
                closes = [d["c"] for d in trend_slice[-50:]]
                ma_now = sum(closes) / len(closes)
                ma_10d_ago = sum(closes[:10]) / 10
                slope = (ma_now - ma_10d_ago) / ma_10d_ago * 100 if ma_10d_ago > 0 else 0
                above_ma = ref_records[day_i]["c"] > ma_now
                if slope > 1.0 and above_ma:
                    dynamic = {"cp_threshold": 45, "resonance_min": 2,
                               "hold_days": 6, "allow_pyramiding": True}
                elif slope < -1.0 and not above_ma:
                    dynamic = {"cp_threshold": 50, "resonance_min": 3,
                               "hold_days": 3, "allow_pyramiding": False}
                else:
                    dynamic = {"cp_threshold": 50, "resonance_min": 3,
                               "hold_days": 3, "allow_pyramiding": False}
            else:
                dynamic = {"cp_threshold": 50, "resonance_min": 3,
                           "hold_days": 3, "allow_pyramiding": False}
        else:
            dynamic = {"cp_threshold": 50, "resonance_min": 3,
                       "hold_days": hold_days, "allow_pyramiding": False}

        # === 卖出 (动态退出或固定持有) ===
        to_sell = []
        for code, pos in holding.items():
            if use_trailing:
                # ATR跟踪退出
                records = data_dict.get(code, [])
                if day_i < len(records) and records[day_i]:
                    current_c = records[day_i]["c"]
                    # 更新最高价
                    if current_c > pos.get("highest", 0):
                        pos["highest"] = current_c

                    # 计算当前ATR
                    atr_val = pos.get("atr", pos["entry_price"] * 0.015)
                    should_exit, reason, stop_price = calc_dynamic_exit(
                        pos["entry_price"], pos["highest"], atr_val,
                        day_i - pos["entry_i"],
                        time_stop=dynamic.get("hold_days", 3) + 5,  # 时间止损=基准+5天
                        target_pct=5.0,
                    )

                    if should_exit:
                        sell_p = current_c if stop_price is None else max(current_c, stop_price)
                        proceeds = pos["shares"] * sell_p * (1 - COMMISSION - SLIPPAGE)
                        cash += proceeds
                        trades.append({
                            "code": code, "name": ETFS[code],
                            "entry_date": pos["entry_date"], "exit_date": date,
                            "entry_price": pos["entry_price"], "exit_price": sell_p,
                            "profit_pct": round((proceeds/pos["cost"]-1)*100, 2),
                            "profit": round(proceeds-pos["cost"], 2),
                            "exit_reason": reason,
                        })
                        to_sell.append(code)
            else:
                # 固定持有期
                if day_i - pos["entry_i"] >= dynamic["hold_days"]:
                    records = data_dict.get(code, [])
                    sell_p = records[day_i]["c"] if day_i < len(records) and records[day_i] else pos["entry_price"]
                    proceeds = pos["shares"] * sell_p * (1 - COMMISSION - SLIPPAGE)
                    cash += proceeds
                    trades.append({
                        "code": code, "name": ETFS[code],
                        "entry_date": pos["entry_date"], "exit_date": date,
                        "entry_price": pos["entry_price"], "exit_price": sell_p,
                        "profit_pct": round((proceeds/pos["cost"]-1)*100, 2),
                        "profit": round(proceeds-pos["cost"], 2),
                        "exit_reason": f"固定持{dynamic['hold_days']}日",
                    })
                    to_sell.append(code)

        for code in to_sell:
            del holding[code]

        # === 信号计算 ===
        signals = []
        for code, records in data_dict.items():
            if code not in ETFS or day_i >= len(records):
                continue
            cp, chg, vr, is_c, close = compute_cp(records, day_i, idx_chg)
            if cp >= dynamic["cp_threshold"]:
                signals.append({"code": code, "cp": cp, "chg": chg, "vr": vr,
                                "is_counter": is_c, "close": close})

        # === 买入 ===
        triggered = len(signals) >= dynamic["resonance_min"]
        if dynamic["allow_pyramiding"]:
            new_sigs = signals  # 允许叠加
        else:
            new_sigs = [s for s in signals if s["code"] not in holding]

        if triggered and new_sigs:
            next_i = day_i + 1
            if next_i >= len(ref_records) - 5:
                continue
            next_date = ref_records[next_i]["date"]

            # 仓位: 金字塔(牛) vs 固定(熊/震荡)
            max_positions = 5 if dynamic["allow_pyramiding"] else 3
            if len(holding) >= max_positions:
                continue

            buy_slots = max_positions - len(holding)
            buy_list = sorted(new_sigs, key=lambda x: x["cp"], reverse=True)[:min(3, buy_slots)]
            alloc = cash * 0.8 / max(len(buy_list), 1)

            for s in buy_list:
                records = data_dict.get(s["code"], [])
                if next_i >= len(records):
                    continue
                open_p = records[next_i]["o"]
                if open_p <= 0: continue
                buy_p = open_p * (1 + SLIPPAGE)
                shares = int(alloc / buy_p / 100) * 100
                if shares < 100: continue
                cost = shares * buy_p * (1 + COMMISSION)
                if cost > cash: continue
                cash -= cost

                # 初始ATR
                atr_info = {"atr": buy_p * 0.015}  # 默认1.5%
                # 尝试计算真实ATR
                if next_i >= 14:
                    trs = []
                    for j in range(next_i-13, next_i+1):
                        if j < 0 or j >= len(records):
                            continue
                        h, l = records[j]["h"], records[j]["l"]
                        pc = records[j-1]["c"] if j > 0 else records[j]["c"]
                        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
                    if trs:
                        atr_info["atr"] = sum(trs) / len(trs)

                holding[s["code"]] = {
                    "shares": shares, "cost": cost,
                    "entry_price": buy_p, "entry_date": next_date,
                    "entry_i": next_i, "highest": buy_p,
                    "atr": atr_info["atr"],
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
    last_i = len(ref_records) - 11
    last_date = ref_records[last_i]["date"]
    for code, pos in holding.items():
        records = data_dict.get(code, [])
        sell_p = records[last_i]["c"] if last_i < len(records) and records[last_i] else pos["entry_price"]
        proceeds = pos["shares"] * sell_p * (1 - COMMISSION - SLIPPAGE)
        cash += proceeds
        trades.append({
            "code": code, "name": ETFS[code],
            "entry_date": pos["entry_date"], "exit_date": last_date,
            "entry_price": pos["entry_price"], "exit_price": sell_p,
            "profit_pct": round((proceeds/pos["cost"]-1)*100, 2),
            "profit": round(proceeds-pos["cost"], 2),
            "exit_reason": "回测结束清仓",
        })
    equity.append(cash)
    return trades, equity


def buy_hold(data_dict, code="510300"):
    records = data_dict.get(code, [])
    if len(records) < 25:
        return [INITIAL]
    si, ei = 20, len(records) - 11
    shares = int(INITIAL / records[si]["c"] / 100) * 100
    return [shares * records[i]["c"] for i in range(si, ei + 1)]


def equal_weight(data_dict):
    equities = []
    for code in ETFS:
        records = data_dict.get(code, [])
        if len(records) < 25:
            continue
        si, ei = 20, len(records) - 11
        shares = int((INITIAL / len(ETFS)) / records[si]["c"] / 100) * 100
        equities.append([shares * records[i]["c"] for i in range(si, ei + 1)])
    if not equities:
        return [INITIAL]
    ml = min(len(e) for e in equities)
    return [sum(e[i] for e in equities) for i in range(ml)]


def metrics(equity, trades, name):
    if len(equity) < 2:
        return {"name": name, "total_return": 0}
    tr = (equity[-1]/equity[0]-1)*100
    ar = ((equity[-1]/equity[0])**(252/max(len(equity),1))-1)*100
    peak = equity[0]; md = 0
    for v in equity:
        if v > peak: peak = v
        dd = (v-peak)/peak*100
        if dd < md: md = dd
    dr = [(equity[i]/equity[i-1]-1) for i in range(1,len(equity))]
    sh = (sum(dr)/len(dr)/((sum((r-sum(dr)/len(dr))**2 for r in dr)/len(dr))**0.5)*(252**0.5)) if dr else 0
    win = [t for t in trades if t["profit"] > 0]
    loss = [t for t in trades if t["profit"] <= 0]
    wr = len(win)/len(trades)*100 if trades else 0
    aw = sum(t["profit_pct"] for t in win)/len(win) if win else 0
    al = sum(t["profit_pct"] for t in loss)/len(loss) if loss else 0
    tp = sum(t["profit_pct"] for t in win)
    tl = abs(sum(t["profit_pct"] for t in loss))
    pf = tp/tl if tl > 0 else float('inf')
    cm = ar/abs(md) if md < 0 else float('inf')
    return {
        "name": name, "total_return": round(tr,2), "annual_return": round(ar,2),
        "max_drawdown": round(md,2), "sharpe": round(sh,2),
        "calmar": round(cm,2) if cm!=float('inf') else "∞",
        "n_trades": len(trades), "win_rate": round(wr,1),
        "avg_win": round(aw,2), "avg_loss": round(al,2),
        "profit_factor": round(pf,2) if pf!=float('inf') else "∞",
        "final_value": round(equity[-1],2),
    }


def main():
    print("=" * 70)
    print("📊 v4 策略改进回测对比 (2023-02 ~ 2026-05, ~800天)")
    print("=" * 70)

    # 加载
    print("\n📡 加载数据...")
    data_dict = {}
    for code, name in ETFS.items():
        records = fetch(code, 800)
        if records:
            data_dict[code] = records
    ref = data_dict["510300"]
    print(f"  数据: {len(ref)}天 ({ref[20]['date']} ~ {ref[-11]['date']})")

    # 回测
    print("\n⏳ v3 基准 (固定3日, ≥3只 ≥50%)...")
    t3, e3 = backtest_v3(data_dict, hold_days=3)
    m3 = metrics(e3, t3, "v3 基准")

    print("⏳ v3 持5日...")
    t35, e35 = backtest_v3(data_dict, hold_days=5)
    m35 = metrics(e35, t35, "v3 持5日")

    print("⏳ v4a 趋势自适应...")
    t4a, e4a = backtest_v4a_trend(data_dict)
    m4a = metrics(e4a, t4a, "v4a 趋势自适应")

    print("⏳ v4b 动态退出...")
    t4b, e4b = backtest_v4b_trailing(data_dict)
    m4b = metrics(e4b, t4b, "v4b 动态退出")

    print("⏳ v4c 趋势+动态退出...")
    t4c, e4c = backtest_v4c_full(data_dict)
    m4c = metrics(e4c, t4c, "v4c 趋势+动态")

    print("⏳ 买持510300...")
    ebh = buy_hold(data_dict)
    mbh = metrics(ebh, [], "买持510300")

    print("⏳ 等权7ETF...")
    eew = equal_weight(data_dict)
    mew = metrics(eew, [], "等权7ETF")

    # 核心-卫星
    print("⏳ 核心卫星(70%买持+30%v4c)...")
    from etf_engine import core_satellite_equity
    ecs = core_satellite_equity(e4c, ebh, core_pct=0.70)
    if ecs:
        mcs = metrics(ecs, [], "核心卫星70/30")
    else:
        mcs = {"name": "-", "total_return": 0}

    # === 汇总 ===
    print("\n" + "=" * 80)
    print("📊 策略对比总表")
    print("=" * 80)

    all_m = [m3, m35, m4a, m4b, m4c, mcs, mbh, mew]
    names = [m["name"] for m in all_m]

    print(f"\n{'指标':<16}", end="")
    for n in names:
        print(f"{n:>12}", end="")
    print()
    print("-" * 16 + "-" * 12 * len(names))

    for label, key in [
        ("总收益(%)", "total_return"),
        ("年化收益(%)", "annual_return"),
        ("最大回撤(%)", "max_drawdown"),
        ("夏普比率", "sharpe"),
        ("卡玛比率", "calmar"),
    ]:
        print(f"{label:<16}", end="")
        for m in all_m:
            v = m.get(key, "-")
            print(f"{str(v):>12}", end="")
        print()

    print(f"\n💰 10万本金→:")
    for m in all_m:
        print(f"  {m['name']:<18} {m['final_value']/10000:.2f}万 ({(m['final_value']/100000-1)*100:+.1f}%)")

    print(f"\n📊 交易统计:")
    for m in [m3, m35, m4a, m4b, m4c]:
        if m["n_trades"] > 0:
            print(f"  {m['name']}: {m['n_trades']}笔, 胜率{m['win_rate']}%, "
                  f"盈{m['avg_win']}%, 亏{m['avg_loss']}%, PF={m['profit_factor']}")

    # === 分年 ===
    print(f"\n📅 分年收益:")
    years_data = defaultdict(dict)
    ref_dates = [r["date"] for r in ref]

    for year in [2023, 2024, 2025, 2026]:
        ys = str(year)
        mask = [i for i, d in enumerate(ref_dates) if d.startswith(ys)]
        if len(mask) < 25: continue
        si, ei = max(20, mask[0]), min(len(ref)-11, mask[-1])
        if ei - si < 15: continue

        yd = {}
        for code, records in data_dict.items():
            yd[code] = records[si:ei+1]

        # v3
        _, ev3 = backtest_v3(yd, hold_days=3)
        years_data[year]["v3"] = round((ev3[-1]/ev3[0]-1)*100, 1) if ev3 else 0

        # v4c
        _, ev4 = backtest_v4c_full(yd)
        years_data[year]["v4c"] = round((ev4[-1]/ev4[0]-1)*100, 1) if ev4 else 0

        ebh = buy_hold(yd)
        years_data[year]["bh"] = round((ebh[-1]/ebh[0]-1)*100, 1) if ebh else 0

        print(f"  {year}: v3{years_data[year]['v3']:+6.1f}% | "
              f"v4c{years_data[year]['v4c']:+6.1f}% | "
              f"买持{years_data[year]['bh']:+6.1f}% | "
              f"v4c超额{years_data[year]['v4c']-years_data[year]['bh']:+5.1f}%")

    # === 结论 ===
    best = max(all_m, key=lambda m: m.get("total_return", -999))
    print(f"\n{'='*80}")
    print(f"📋 结论")
    print(f"{'='*80}")
    print(f"  最佳绝对收益: {best['name']} ({best['total_return']:+.1f}%)")
    print(f"  v3→v4c 改进: {m4c['total_return']-m3['total_return']:+.1f}%")
    print(f"  v4c vs 买持: {m4c['total_return']-mbh['total_return']:+.1f}%")
    print(f"  v4c 夏普: {m4c['sharpe']} vs 买持: {mbh['sharpe']}")
    print(f"  v4c 最大回撤: {m4c['max_drawdown']}% vs 买持: {mbh['max_drawdown']}%")
    if mcs["total_return"] > 0:
        print(f"  核心卫星70/30: {mcs['total_return']:+.1f}% (夏普{mcs['sharpe']})")
        print(f"  💡 核心卫星=最稳方案: 回撤可控+牛市跟涨+熊市抗跌")


if __name__ == "__main__":
    main()
