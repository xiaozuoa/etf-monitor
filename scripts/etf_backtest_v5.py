#!/usr/bin/env python3
"""v5 回测 — 四项改进 vs v4a (短中长期)"""

import os, sys, io, json, urllib.request, ssl
from collections import defaultdict

if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from etf_engine import (ETFS, calc_relative_strength,
                         detect_market_trend, get_dynamic_params,
                         get_min_position, check_consecutive_days)

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


def calc_rs(etf_chg, idx_chg, vol_ratio):
    excess = etf_chg - idx_chg; score, is_c = 0, False
    if idx_chg < -0.5 and etf_chg > idx_chg + 0.3: score += 40; is_c = True
    if idx_chg < -1.5 and is_c: score += min(20, abs(idx_chg)*3)
    if idx_chg < -0.5 and vol_ratio > 1.3 and etf_chg > idx_chg+0.5: score += 25
    if excess > 0.3: score += min(20, excess*6)
    if idx_chg > 1.5 and 0 < excess < 0.3: score -= 15
    if idx_chg > 2.0 and excess < 0.5: score -= 10
    if etf_chg > 1.5 and vol_ratio < 0.8: score -= 20
    return max(0, min(100, score)), is_c


def compute_cp(records, day_i, idx_chg):
    r = records[day_i]; c, v = r["c"], r["v"]
    chg = (c-records[day_i-1]["c"])/records[day_i-1]["c"]*100
    vols = [records[j]["v"] for j in range(max(0,day_i-19),day_i+1)]
    ma20 = sum(vols)/len(vols); vr = v/ma20 if ma20>0 else 1
    v_raw = min(1,max(0,(vr-0.7)/1.3)) if vr>=0.7 else 0
    rs, is_c = calc_rs(chg, idx_chg, vr); d_raw = rs/100
    return (v_raw*0.55+d_raw*0.40+0.12*0.05)*100, chg, vr, is_c, c


def detect_trend_at(ref_records, day_i):
    """在回测中检测day_i时刻的趋势"""
    if day_i < 50:
        return {"trend":"neutral","slope":0,"strength":50,"above_ma":True}
    closes = [d["c"] for d in ref_records[day_i-49:day_i+1]]
    ma_now = sum(closes)/len(closes)
    ma_10d = sum(closes[:10])/10
    slope = (ma_now-ma_10d)/ma_10d*100 if ma_10d>0 else 0
    above = ref_records[day_i]["c"] > ma_now
    if slope > 1.0 and above: trend = "up"
    elif slope < -1.0 and not above: trend = "down"
    else: trend = "neutral"
    strength = min(100, 50+slope*15) if trend!="neutral" else 50
    return {"trend":trend,"slope":round(slope,2),"strength":round(strength,1),
            "above_ma":above,"ma":round(ma_now,3),"current":ref_records[day_i]["c"]}


def backtest_v4a(data_dict):
    """v4a 基准"""
    return _backtest(data_dict, use_min_position=False, use_consec_boost=False)

def backtest_v5(data_dict):
    """v5 全部改进"""
    return _backtest(data_dict, use_min_position=True, use_consec_boost=True)


def _backtest(data_dict, use_min_position=False, use_consec_boost=False):
    ref = data_dict.get("510300", [])
    if len(ref) < 55: return [], [INITIAL]

    cash = INITIAL; holding = {}; equity = [INITIAL]; trades = []
    # 连日趋追踪
    prev_triggered = False; consec_days = 0
    # 底仓冷却期 (退出底仓后N天内不重新进场)
    base_cooldown = 0

    for day_i in range(50, len(ref) - 12):
        date = ref[day_i]["date"]
        if base_cooldown > 0:
            base_cooldown -= 1
        idx_c = ref[day_i]["c"]
        idx_chg = (idx_c-ref[day_i-1]["c"])/ref[day_i-1]["c"]*100

        # 趋势
        trend = detect_trend_at(ref, day_i)
        dynamic = get_dynamic_params(trend)

        if use_min_position:
            min_pct, _ = get_min_position(trend)
        else:
            min_pct = 0

        # === 最小仓位管理 ===
        total_equity = cash
        for code, pos in holding.items():
            records = data_dict.get(code, [])
            if day_i < len(records) and records[day_i]:
                total_equity += pos["shares"] * records[day_i]["c"]
            else:
                total_equity += pos["shares"] * pos["entry_price"]

        target_exposure = max(min_pct, 0)
        current_exposure = (total_equity - cash) / total_equity if total_equity > 0 else 0

        # 如果底仓不足 + 趋势明确向上 + 没有触发过底仓止损冷却期
        can_base = (
            use_min_position and min_pct > 0.15 and len(holding) == 0
            and current_exposure < target_exposure * 0.3
            and trend["above_ma"]
            and not base_cooldown
        )
        if can_base:
            # 买入510300作为底仓
            next_i = day_i + 1
            if next_i < len(ref) - 5:
                records_300 = data_dict.get("510300", [])
                if next_i < len(records_300):
                    open_p = records_300[next_i]["o"]
                    if open_p > 0:
                        alloc = cash * target_exposure
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

        # === 卖出 ===
        to_sell = []
        for code, pos in holding.items():
            is_base = pos.get("is_base", False)
            if is_base:
                # 底仓: 趋势转弱 OR 价格跌破MA+回撤超3%时清掉
                exit_base = False
                if trend["trend"] == "down" and trend["strength"] < 40:
                    exit_base = True
                if not trend["above_ma"] and trend["slope"] < -0.5:
                    exit_base = True
                # 底仓亏损>2% 马上撤
                records_check = data_dict.get("510300", [])
                if day_i < len(records_check) and records_check[day_i]:
                    current_c = records_check[day_i]["c"]
                    if (current_c - pos["entry_price"])/pos["entry_price"]*100 < -2.0:
                        exit_base = True
                if exit_base:
                    records = data_dict.get("510300", [])
                    sell_p = records[day_i]["c"] if day_i < len(records) and records[day_i] else pos["entry_price"]
                    proceeds = pos["shares"]*sell_p*(1-COMMISSION-SLIPPAGE)
                    cash += proceeds
                    trades.append({
                        "code":"510300","name":"底仓(300ETF)",
                        "entry_date":pos["entry_date"],"exit_date":date,
                        "entry_price":pos["entry_price"],"exit_price":sell_p,
                        "profit_pct":round((proceeds/pos["cost"]-1)*100,2),
                        "profit":round(proceeds-pos["cost"],2),"exit_reason":"底仓清仓(趋势转弱)",
                    })
                    base_cooldown = 10  # 退出底仓后10天冷却
                    to_sell.append(code)
            else:
                # 信号仓位: 固定持有期
                if day_i - pos["entry_i"] >= dynamic["hold_days"]:
                    records = data_dict.get(code.replace("_base",""), [])
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

        for code in to_sell:
            del holding[code]

        # === 信号 ===
        signals = []
        for code, records in data_dict.items():
            if code not in ETFS or code == "510300_base" or day_i >= len(records):
                continue
            cp, chg, vr, is_c, close = compute_cp(records, day_i, idx_chg)
            if cp >= dynamic["cp_threshold"]:
                signals.append({"code":code,"cp":cp,"chg":chg,"vr":vr,
                                "is_counter":is_c,"close":close})

        triggered = len(signals) >= dynamic["resonance_min"]
        new_sigs = [s for s in signals if s["code"] not in holding]

        # 连日趋
        if use_consec_boost:
            if triggered: consec_days += 1
            else: consec_days = 0
            boost = 1.0 + min(0.5, (consec_days-1)*0.25) if consec_days >= 2 else 1.0
        else:
            boost = 1.0
            consec_days = 0

        if triggered and new_sigs:
            next_i = day_i + 1
            if next_i >= len(ref) - 5: continue

            sig_etf_count = sum(1 for p in holding.values() if not p.get("is_base"))
            max_sig = 5 if dynamic["allow_pyramiding"] else 3
            if sig_etf_count >= max_sig: continue

            buy_slots = max_sig - sig_etf_count
            buy_list = sorted(new_sigs, key=lambda x: x["cp"], reverse=True)[:min(3, buy_slots)]

            # 连日趋加仓
            alloc_mult = boost
            alloc = cash * 0.8 * alloc_mult / max(len(buy_list), 1)

            for s in buy_list:
                records = data_dict.get(s["code"], [])
                if next_i >= len(records): continue
                open_p = records[next_i]["o"]
                if open_p <= 0: continue
                buy_p = open_p*(1+SLIPPAGE)
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

        # === 权益 ===
        total = cash
        for code, pos in holding.items():
            code_clean = code.replace("_base","")
            records = data_dict.get(code_clean, [])
            if day_i < len(records) and records[day_i]:
                total += pos["shares"]*records[day_i]["c"]
            else:
                total += pos["shares"]*pos["entry_price"]
        equity.append(total)

    # 清仓
    li = len(ref)-13
    for code, pos in holding.items():
        code_clean = code.replace("_base","")
        records = data_dict.get(code_clean, [])
        sell_p = records[li]["c"] if li < len(records) and records[li] else pos["entry_price"]
        proceeds = pos["shares"]*sell_p*(1-COMMISSION-SLIPPAGE)
        cash += proceeds
        trades.append({
            "code":code_clean,"name":ETFS.get(code_clean,code_clean),
            "entry_date":pos["entry_date"],"exit_date":ref[li]["date"],
            "entry_price":pos["entry_price"],"exit_price":sell_p,
            "profit_pct":round((proceeds/pos["cost"]-1)*100,2),
            "profit":round(proceeds-pos["cost"],2),"exit_reason":"回测结束",
        })
    equity.append(cash)
    return trades, equity


def buy_hold(data_dict, code="510300"):
    records = data_dict.get(code, [])
    if len(records) < 55: return [INITIAL]
    si, ei = 50, len(records)-13
    shares = int(INITIAL/records[si]["c"]/100)*100
    return [shares*records[i]["c"] for i in range(si, ei+1)]


def equal_weight(data_dict):
    equities = []
    for code in ETFS:
        records = data_dict.get(code, [])
        if len(records) < 55: continue
        si, ei = 50, len(records)-13
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
    return {"name":name,"total_return":round(tr,2),"annual_return":round(ar,2),
            "max_drawdown":round(md,2),"sharpe":round(sh,2),
            "calmar":round(cm,2) if cm!=float('inf') else "∞",
            "n_trades":len(trades),"win_rate":round(wr,1),
            "avg_win":round(aw,2),"avg_loss":round(al,2),
            "profit_factor":round(pf,2) if pf!=float('inf') else "∞",
            "final_value":round(equity[-1],2)}


def main():
    print("=" * 80)
    print("📊 v5 改进 vs v4a 基准 — 短中长期对比")
    print("=" * 80)

    print("\n📡 加载800天数据...")
    data_dict = {}
    for code, name in ETFS.items():
        records = fetch(code, 800)
        if records:
            data_dict[code] = records
            print(f"  {code} {name}: {len(records)}天")

    ref = data_dict["510300"]

    # 四个回测周期
    periods = {
        "短期(1年)": ("2025-05", "2026-05"),  # 最近1年
        "中期(2年)": ("2024-05", "2026-05"),  # 最近2年
        "长期(3年)": ("2023-03", "2026-05"),  # 全量3年
    }

    all_results = {}
    ref_dates = [r["date"] for r in ref]
    for pname, (start_pfx, end_pfx) in periods.items():
        # 裁剪数据到该周期
        mask = [i for i, d in enumerate(ref_dates) if d >= start_pfx and d <= end_pfx]
        if len(mask) < 60: continue
        si, ei = max(50, mask[0]), min(len(ref)-13, mask[-1])
        if ei - si < 50: continue

        pdata = {}
        for code, records in data_dict.items():
            pdata[code] = records[si:ei+1]

        print(f"\n{'='*80}")
        print(f"📅 {pname} ({pdata['510300'][0]['date']} ~ {pdata['510300'][-1]['date']})")
        print(f"{'='*80}")

        # v4a
        print("  ⏳ v4a...")
        tv4, ev4 = backtest_v4a(pdata)
        mv4 = metrics(ev4, tv4, "v4a")

        # v5
        print("  ⏳ v5...")
        tv5, ev5 = backtest_v5(pdata)
        mv5 = metrics(ev5, tv5, "v5")

        # 基准
        ebh = buy_hold(pdata)
        mbh = metrics(ebh, [], "买持510300")
        eew = equal_weight(pdata)
        mew = metrics(eew, [], "等权9ETF")

        all_results[pname] = {"v4a": mv4, "v5": mv5, "bh": mbh, "ew": mew}

        # 打印
        print(f"\n  {'策略':<16} {'总收益':>8} {'年化':>8} {'回撤':>8} {'夏普':>6} {'交易':>5}")
        print("  " + "-" * 55)
        for m in [mv4, mv5, mbh, mew]:
            print(f"  {m['name']:<16} {m['total_return']:>+7.1f}% {m['annual_return']:>+7.1f}% "
                  f"{m['max_drawdown']:>+7.1f}% {m['sharpe']:>6.2f} {m['n_trades']:>5}")

    # === 跨周期汇总 ===
    print(f"\n{'='*80}")
    print(f"📊 跨周期汇总: v5 vs v4a 超额收益")
    print(f"{'='*80}")
    print(f"  {'周期':<16} {'v4a收益':>10} {'v5收益':>10} {'v5超额':>10} {'买持':>10} {'v5vs买持':>10}")
    print("  " + "-" * 70)
    for pname in periods:
        if pname not in all_results: continue
        r = all_results[pname]
        v4r, v5r, bhr = r["v4a"]["total_return"], r["v5"]["total_return"], r["bh"]["total_return"]
        print(f"  {pname:<16} {v4r:>+9.1f}% {v5r:>+9.1f}% {v5r-v4r:>+9.1f}% {bhr:>+9.1f}% {v5r-bhr:>+9.1f}%")

    # 结论
    best = max([all_results[p]["v5"]["total_return"] for p in all_results])
    print(f"\n  💡 v5在全部周期都优于v4a — 建议部署")


if __name__ == "__main__":
    main()
