#!/usr/bin/env python3
"""v6 — 底仓止损 + 信号加权仓位 + 卖出信号 (vs v5)"""

import os, sys, io, json, urllib.request, ssl
from collections import defaultdict

if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from etf_engine import (ETFS, calc_atr,
                         get_dynamic_params,
                         get_min_position)
from etf_signals import compute_cp, detect_trend, calc_rs

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False; SSL_CTX.verify_mode = ssl.CERT_NONE
COMMISSION = 0.00025; SLIPPAGE = 0.0005; INITIAL = 100000


def fetch(code, limit=800):
    pfx = "sh" if code.startswith(("51","56","0")) else "sz"
    if code.startswith("sh") or code.startswith("sz"):
        pfx, numcode = code[:2], code[2:]
    else: numcode = code
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={pfx}{numcode},day,,,{limit},qfq"
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as r:
            d = json.loads(r.read().decode("utf-8"))
        k = d.get("data",{}).get(f"{pfx}{numcode}",{}).get("qfqday",[]) or \
            d.get("data",{}).get(f"{pfx}{numcode}",{}).get("day",[])
        return [{"date":r[0],"o":float(r[1]),"c":float(r[2]),
                 "h":float(r[3]),"l":float(r[4]),"v":float(r[5])}
                for r in k if len(r)>=6 and r[0]]
    except: return []




def get_signal_position_weight(cp, consec_days):
    """v6: 根据信号强度分配仓位权重。CP越高,仓位越大。连日趋额外加码。"""
    if cp >= 70:   base = 1.0
    elif cp >= 60: base = 0.75
    elif cp >= 50: base = 0.55
    else:          base = 0.40

    # 连日趋加成
    if consec_days >= 3: base *= 1.5
    elif consec_days >= 2: base *= 1.25
    return base


def backtest_v5(data_dict):
    """v5 基准"""
    return _backtest(data_dict, use_better_base=False, use_weighted_pos=False)

def backtest_v6(data_dict):
    """v6: 底仓风控 + 信号加权"""
    return _backtest(data_dict, use_better_base=True, use_weighted_pos=True)


def _backtest(data_dict, use_better_base=False, use_weighted_pos=False):
    ref = data_dict.get("510300", [])
    if len(ref) < 65: return [], [INITIAL]

    cash = INITIAL; holding = {}; equity = [INITIAL]; trades = []
    base_cooldown = 0; consec_days = 0; prev_triggered = False
    base_entry_price = 0  # 用于底仓止损

    for day_i in range(60, len(ref) - 12):
        date = ref[day_i]["date"]
        if base_cooldown > 0: base_cooldown -= 1
        idx_c = ref[day_i]["c"]
        idx_chg = (idx_c-ref[day_i-1]["c"])/ref[day_i-1]["c"]*100

        trend = detect_trend(ref, day_i)
        dynamic = get_dynamic_params(trend)
        if use_better_base:
            min_pct, _ = get_min_position(trend)
        else:
            min_pct = 0

        # === v6 底仓风控 ===
        total_equity = cash
        for code, pos in holding.items():
            lookup_code = code.replace("_base", "")
            records = data_dict.get(lookup_code, [])
            if day_i < len(records) and records[day_i]:
                total_equity += pos["shares"] * records[day_i]["c"]
            else:
                total_equity += pos["shares"] * pos["entry_price"]

        current_exposure = (total_equity - cash) / total_equity if total_equity > 0 else 0

        if use_better_base:
            # 更严格的底仓条件
            can_base = (
                min_pct > 0.15 and len(holding) == 0
                and current_exposure < 0.1
                and trend["above_ma"]
                and trend["strength"] > 55
                and not base_cooldown
            )
            # 保守仓位: 最多30%
            target_base_pct = min(0.30, min_pct * 0.6)
        else:
            can_base = (min_pct > 0 and len(holding) == 0 and current_exposure < 0.3
                        and not base_cooldown)
            target_base_pct = min_pct

        if can_base:
            next_i = day_i + 1
            if next_i < len(ref) - 5:
                r300 = data_dict.get("510300", [])
                if next_i < len(r300):
                    open_p = r300[next_i]["o"]
                    if open_p > 0:
                        alloc = cash * target_base_pct
                        buy_p = open_p * (1+SLIPPAGE)
                        shares = int(alloc/buy_p/100)*100
                        if shares >= 100:
                            cost = shares*buy_p*(1+COMMISSION)
                            if cost <= cash:
                                cash -= cost
                                holding["510300_base"] = {
                                    "shares":shares,"cost":cost,
                                    "entry_price":buy_p,"entry_date":ref[next_i]["date"],
                                    "entry_i":next_i,"highest":buy_p,"is_base":True,
                                }
                                base_entry_price = buy_p

        # === 卖出 ===
        to_sell = []
        for code, pos in holding.items():
            if pos.get("is_base"):
                exit_base = False
                records_b = data_dict.get("510300", [])
                cur_c = records_b[day_i]["c"] if day_i < len(records_b) and records_b[day_i] else pos["entry_price"]

                # 底仓退出: 趋势转弱 或 跌破MA 或 亏>2%
                if trend["trend"] == "down" and trend["strength"] < 40:
                    exit_base = True
                if use_better_base:
                    if not trend["above_ma"] and trend["slope"] < -0.5: exit_base = True
                    if (cur_c - pos["entry_price"])/pos["entry_price"]*100 < -2.5: exit_base = True
                else:
                    if not trend["above_ma"]: exit_base = True
                    if (cur_c - pos["entry_price"])/pos["entry_price"]*100 < -3.0: exit_base = True

                if exit_base:
                    sell_p = cur_c
                    proceeds = pos["shares"]*sell_p*(1-COMMISSION-SLIPPAGE)
                    cash += proceeds
                    trades.append({
                        "code":"510300","name":"底仓",
                        "entry_date":pos["entry_date"],"exit_date":date,
                        "entry_price":pos["entry_price"],"exit_price":sell_p,
                        "profit_pct":round((proceeds/pos["cost"]-1)*100,2),
                        "profit":round(proceeds-pos["cost"],2),
                        "exit_reason":"底仓清仓(趋势转弱/止损)",
                    })
                    base_cooldown = 15 if use_better_base else 10
                    to_sell.append(code)
            else:
                if day_i - pos["entry_i"] >= dynamic["hold_days"]:
                    records = data_dict.get(code, [])
                    sell_p = records[day_i]["c"] if day_i < len(records) and records[day_i] else pos["entry_price"]
                    proceeds = pos["shares"]*sell_p*(1-COMMISSION-SLIPPAGE)
                    cash += proceeds
                    trades.append({
                        "code":code,"name":ETFS.get(code,code),
                        "entry_date":pos["entry_date"],"exit_date":date,
                        "entry_price":pos["entry_price"],"exit_price":sell_p,
                        "profit_pct":round((proceeds/pos["cost"]-1)*100,2),
                        "profit":round(proceeds-pos["cost"],2),
                        "exit_reason":f"持有{dynamic['hold_days']}日到期",
                    })
                    to_sell.append(code)

        for code in to_sell: del holding[code]

        # === 信号 ===
        signals = []
        for code, records in data_dict.items():
            if code not in ETFS or day_i >= len(records): continue
            cp, chg, vr, is_c, close = compute_cp(records, day_i, idx_chg)
            if cp >= dynamic["cp_threshold"]:
                signals.append({"code":code,"cp":cp,"chg":chg,"vr":vr,
                                "is_counter":is_c,"close":close})

        triggered = len(signals) >= dynamic["resonance_min"]
        new_sigs = [s for s in signals if s["code"] not in holding]

        if triggered: consec_days += 1
        else: consec_days = 0

        if triggered and new_sigs:
            next_i = day_i + 1
            if next_i >= len(ref) - 5: continue

            sig_count = sum(1 for p in holding.values() if not p.get("is_base"))
            max_sig = 5 if dynamic["allow_pyramiding"] else 3
            if sig_count >= max_sig: continue

            buy_slots = max_sig - sig_count
            buy_list = sorted(new_sigs, key=lambda x: x["cp"], reverse=True)[:min(3, buy_slots)]

            total_budget = cash * 0.8
            # 计算每个标的的权重
            weights_list = []
            for s in buy_list:
                if use_weighted_pos:
                    w = get_signal_position_weight(s["cp"], consec_days)
                else:
                    w = 1.0
                weights_list.append(w)
            weight_sum = sum(weights_list)

            for s, w in zip(buy_list, weights_list):
                records = data_dict.get(s["code"], [])
                if next_i >= len(records): continue
                open_p = records[next_i]["o"]
                if open_p <= 0: continue
                buy_p = open_p*(1+SLIPPAGE)
                alloc = total_budget / len(buy_list) * (w / max(weight_sum/len(buy_list), 0.1))
                alloc = min(alloc, total_budget * 0.5)  # 单只最多50%
                shares = int(alloc/buy_p/100)*100
                if shares < 100: continue
                cost = shares*buy_p*(1+COMMISSION)
                if cost > cash: continue
                cash -= cost
                holding[s["code"]] = {
                    "shares":shares,"cost":cost,
                    "entry_price":buy_p,"entry_date":ref[next_i]["date"],
                    "entry_i":next_i,"highest":buy_p,
                }

        # 权益
        total = cash
        for code, pos in holding.items():
            code_c = code.replace("_base","")
            records = data_dict.get(code_c, [])
            if day_i < len(records) and records[day_i]:
                total += pos["shares"]*records[day_i]["c"]
            else:
                total += pos["shares"]*pos["entry_price"]
        equity.append(total)

    # 清仓
    li = len(ref)-13
    for code, pos in holding.items():
        code_c = code.replace("_base","")
        records = data_dict.get(code_c, [])
        sell_p = records[li]["c"] if li < len(records) and records[li] else pos["entry_price"]
        proceeds = pos["shares"]*sell_p*(1-COMMISSION-SLIPPAGE)
        cash += proceeds
        trades.append({
            "code":code_c,"name":ETFS.get(code_c,code_c),
            "entry_date":pos["entry_date"],"exit_date":ref[li]["date"],
            "entry_price":pos["entry_price"],"exit_price":sell_p,
            "profit_pct":round((proceeds/pos["cost"]-1)*100,2),
            "profit":round(proceeds-pos["cost"],2),"exit_reason":"回测结束",
        })
    equity.append(cash)
    return trades, equity


def buy_hold(data_dict, code="510300"):
    records = data_dict.get(code, [])
    if len(records) < 65: return [INITIAL]
    si, ei = 60, len(records)-13
    shares = int(INITIAL/records[si]["c"]/100)*100
    return [shares*records[i]["c"] for i in range(si, ei+1)]


def equal_weight(data_dict):
    equities = []
    for code in ETFS:
        records = data_dict.get(code, [])
        if len(records) < 65: continue
        si, ei = 60, len(records)-13
        shares = int((INITIAL/len(ETFS))/records[si]["c"]/100)*100
        equities.append([shares*records[i]["c"] for i in range(si, ei+1)])
    if not equities: return [INITIAL]
    ml = min(len(e) for e in equities)
    return [sum(e[i] for e in equities) for i in range(ml)]


def metrics(equity, trades, name):
    if len(equity) < 2: return {"name":name,"total_return":0}
    tr = (equity[-1]/equity[0]-1)*100
    ar = ((equity[-1]/equity[0])**(252/max(len(equity),1))-1)*100
    peak=equity[0]; md=0
    for v in equity:
        if v>peak: peak=v
        dd=(v-peak)/peak*100
        if dd<md: md=dd
    dr=[(equity[i]/equity[i-1]-1) for i in range(1,len(equity))]
    sh=(sum(dr)/len(dr)/((sum((r-sum(dr)/len(dr))**2 for r in dr)/len(dr))**0.5)*(252**0.5)) if dr else 0
    win=[t for t in trades if t["profit"]>0]
    loss=[t for t in trades if t["profit"]<=0]
    wr=len(win)/len(trades)*100 if trades else 0
    aw=sum(t["profit_pct"] for t in win)/len(win) if win else 0
    al=sum(t["profit_pct"] for t in loss)/len(loss) if loss else 0
    tp=sum(t["profit_pct"] for t in win); tl=abs(sum(t["profit_pct"] for t in loss))
    pf=tp/tl if tl>0 else float('inf')
    cm=ar/abs(md) if md<0 else float('inf')
    # 计算交易胜率加权后的统计
    avg_return_per_trade = sum(t["profit_pct"] for t in trades)/len(trades) if trades else 0
    return {"name":name,"total_return":round(tr,2),"annual_return":round(ar,2),
            "max_drawdown":round(md,2),"sharpe":round(sh,2),
            "calmar":round(cm,2) if cm!=float('inf') else "∞",
            "n_trades":len(trades),"win_rate":round(wr,1),
            "avg_win":round(aw,2),"avg_loss":round(al,2),
            "profit_factor":round(pf,2) if pf!=float('inf') else "∞",
            "avg_trade":round(avg_return_per_trade,2),
            "final_value":round(equity[-1],2)}


def main():
    print("=" * 80)
    print("📊 v6 改进 (底仓风控 + 信号加权) vs v5")
    print("=" * 80)

    print("\n📡 加载800天数据...")
    data_dict = {}
    for code, name in ETFS.items():
        records = fetch(code, 800)
        if records: data_dict[code] = records

    ref = data_dict["510300"]
    ref_dates = [r["date"] for r in ref]

    periods = {
        "短期(1年)": ("2025-05", "2026-05"),
        "中期(2年)": ("2024-05", "2026-05"),
        "长期(3年)": ("2023-03", "2026-05"),
    }

    all_results = {}
    for pname, (spfx, epfx) in periods.items():
        mask = [i for i, d in enumerate(ref_dates) if d >= spfx and d <= epfx]
        if len(mask) < 60: continue
        si, ei = max(60, mask[0]), min(len(ref)-13, mask[-1])
        if ei - si < 50: continue

        pdata = {}
        for code, records in data_dict.items():
            pdata[code] = records[si:ei+1]

        print(f"\n{'='*80}")
        print(f"📅 {pname} ({pdata['510300'][0]['date']} ~ {pdata['510300'][-1]['date']})")
        print(f"{'='*80}")

        print("  ⏳ v5...")
        tv5, ev5 = backtest_v5(pdata)
        mv5 = metrics(ev5, tv5, "v5")

        print("  ⏳ v6...")
        tv6, ev6 = backtest_v6(pdata)
        mv6 = metrics(ev6, tv6, "v6")

        ebh = buy_hold(pdata)
        mbh = metrics(ebh, [], "买持510300")

        all_results[pname] = {"v5": mv5, "v6": mv6, "bh": mbh}

        print(f"\n  {'策略':<14} {'总收益':>8} {'年化':>8} {'回撤':>8} {'夏普':>6} {'卡玛':>6} {'交易':>5} {'均盈':>6}")
        print("  " + "-" * 65)
        for m in [mv5, mv6, mbh]:
            at = m.get("avg_trade", 0)
            print(f"  {m['name']:<14} {m['total_return']:>+7.1f}% {m['annual_return']:>+7.1f}% "
                  f"{m['max_drawdown']:>+7.1f}% {m['sharpe']:>6.2f} {m['calmar']:>6} "
                  f"{m['n_trades']:>5} {m['avg_win']:>+5.1f}%")

    # 汇总
    print(f"\n{'='*80}")
    print(f"📊 v6 vs v5 跨周期汇总")
    print(f"{'='*80}")
    print(f"  {'周期':<16} {'v5收益':>8} {'v6收益':>8} {'v6超额':>8} {'v5回撤':>8} {'v6回撤':>8} {'回撤改善':>8} {'买持':>8}")
    print("  " + "-" * 76)
    for pname in periods:
        if pname not in all_results: continue
        r = all_results[pname]
        dd_improve = r["v6"]["max_drawdown"] - r["v5"]["max_drawdown"]
        print(f"  {pname:<16} {r['v5']['total_return']:>+7.1f}% {r['v6']['total_return']:>+7.1f}% "
              f"{r['v6']['total_return']-r['v5']['total_return']:>+7.1f}% "
              f"{r['v5']['max_drawdown']:>+7.1f}% {r['v6']['max_drawdown']:>+7.1f}% "
              f"{dd_improve:>+7.1f}% {r['bh']['total_return']:>+7.1f}%")

    # 最优
    best3y = all_results.get("长期(3年)", {})
    if best3y:
        v6_3y = best3y["v6"]
        v5_3y = best3y["v5"]
        print(f"\n  📌 v6改进效果: 收益{v6_3y['total_return']-v5_3y['total_return']:+.1f}% | "
              f"回撤{v6_3y['max_drawdown']-v5_3y['max_drawdown']:+.1f}% | "
              f"夏普{v6_3y['sharpe']-v5_3y['sharpe']:+.2f}")


if __name__ == "__main__":
    main()
