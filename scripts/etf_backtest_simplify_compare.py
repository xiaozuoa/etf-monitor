#!/usr/bin/env python3
"""简化模型 vs 当前复杂模型 — 长中短期对比回测"""

import os, sys, io
from collections import defaultdict

if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from etf_engine import ETFS
from etf_signals import fetch, detect_trend, calc_rs, compute_cp, COMMISSION, SLIPPAGE, INITIAL


# ============================================================
# 模型定义
# ============================================================

def get_config_current(trend, above_ma):
    """当前复杂模型: 4套参数, 4212网格搜索最优"""
    t = trend["trend"]
    if t == "up":
        return {"cp_threshold":45,"resonance_min":2,"hold_days":10,
                "allow_pyramiding":True, "label":"up(宽松)"}
    elif t == "down":
        return {"cp_threshold":50,"resonance_min":4,"hold_days":4,
                "allow_pyramiding":False, "label":"down(防御)"}
    else:  # neutral
        if above_ma:
            return {"cp_threshold":50,"resonance_min":2,"hold_days":7,
                    "allow_pyramiding":False, "label":"中性偏多"}
        else:
            return {"cp_threshold":50,"resonance_min":5,"hold_days":4,
                    "allow_pyramiding":False, "label":"中性偏空"}

def get_min_position_current(trend):
    """当前模型底仓"""
    s = trend["strength"]; t = trend["trend"]
    if s >= 70: return 0.40
    elif s >= 50:
        if t == "up": return 0.25
        else: return 0.15
    elif s >= 30:
        if t == "down": return 0.0
        else: return 0.10
    else: return 0.0


def get_config_simple(trend, above_ma):
    """简化模型: 仅2套参数 (上涨 vs 其他)"""
    t = trend["trend"]
    if t == "up":
        return {"cp_threshold":50,"resonance_min":2,"hold_days":7,
                "allow_pyramiding":True, "label":"up"}
    else:
        return {"cp_threshold":50,"resonance_min":3,"hold_days":5,
                "allow_pyramiding":False, "label":"other"}

def get_min_position_simple(trend):
    """简化底仓: 仅上涨趋势有底仓"""
    if trend["trend"] == "up" and trend["strength"] >= 60:
        return 0.25
    return 0.0


# ============================================================
# 统一回测引擎
# ============================================================

def backtest(data_dict, model_name):
    """统一回测框架"""
    if model_name == "simplified":
        cfg_fn = get_config_simple
        base_fn = get_min_position_simple
    else:
        cfg_fn = get_config_current
        base_fn = get_min_position_current

    ref = data_dict.get("510300", [])
    if len(ref) < 65: return [], [INITIAL]

    cash = INITIAL; holding = {}; equity = [INITIAL]; trades = []
    base_cooldown = 0

    for day_i in range(60, len(ref) - 12):
        date = ref[day_i]["date"]
        if base_cooldown > 0: base_cooldown -= 1

        idx_c = ref[day_i]["c"]
        idx_chg = (idx_c-ref[day_i-1]["c"])/ref[day_i-1]["c"]*100

        trend = detect_trend(ref, day_i)
        cfg = cfg_fn(trend, trend["above_ma"])
        min_pct = base_fn(trend)

        # --- 卖出 ---
        to_sell = []
        for code, pos in holding.items():
            if pos.get("is_base"):
                records_b = data_dict.get("510300", [])
                cur_c = records_b[day_i]["c"] if day_i < len(records_b) and records_b[day_i] else pos["entry_price"]
                exit_base = False
                if trend["trend"] == "down" and trend["strength"] < 40: exit_base = True
                if not trend["above_ma"] and trend["slope"] < -0.5: exit_base = True
                if (cur_c-pos["entry_price"])/pos["entry_price"]*100 < -2.5: exit_base = True
                if exit_base:
                    sp = cur_c; pr = pos["shares"]*sp*(1-COMMISSION-SLIPPAGE); cash += pr
                    trades.append({"profit_pct":round((pr/pos["cost"]-1)*100,2)})
                    base_cooldown = 15; to_sell.append(code)
            else:
                if day_i - pos["entry_i"] >= cfg["hold_days"]:
                    recs = data_dict.get(code, [])
                    sp = recs[day_i]["c"] if day_i < len(recs) and recs[day_i] else pos["entry_price"]
                    pr = pos["shares"]*sp*(1-COMMISSION-SLIPPAGE); cash += pr
                    trades.append({"profit_pct":round((pr/pos["cost"]-1)*100,2)})
                    to_sell.append(code)
        for code in to_sell: del holding[code]

        # --- 底仓 ---
        total_eq = cash
        for code, pos in holding.items():
            recs = data_dict.get(code, data_dict.get("510300", []))
            if day_i < len(recs) and recs[day_i]: total_eq += pos["shares"]*recs[day_i]["c"]
            else: total_eq += pos["shares"]*pos["entry_price"]
        cur_exp = (total_eq-cash)/total_eq if total_eq > 0 else 0

        can_base = (min_pct > 0 and len(holding) == 0 and cur_exp < 0.3
                    and trend["above_ma"] and not base_cooldown)
        if can_base:
            next_i = day_i + 1
            if next_i < len(ref) - 5:
                r300 = data_dict.get("510300", [])
                if next_i < len(r300):
                    op = r300[next_i]["o"]
                    if op > 0:
                        alloc = cash * min_pct
                        bp = op*(1+SLIPPAGE); sh = int(alloc/bp/100)*100
                        if sh >= 100:
                            cost = sh*bp*(1+COMMISSION)
                            if cost <= cash:
                                cash -= cost
                                holding["510300_base"] = {"shares":sh,"cost":cost,
                                    "entry_price":bp,"entry_date":ref[next_i]["date"],
                                    "entry_i":next_i,"highest":bp,"is_base":True}

        # --- 信号检测 ---
        signals = []
        for code, recs in data_dict.items():
            if code not in ETFS or day_i >= len(recs): continue
            cp, chg, vr, is_c, close = compute_cp(recs, day_i, idx_chg)
            if cp >= cfg["cp_threshold"]:
                signals.append({"code":code,"cp":cp})

        triggered = len(signals) >= cfg["resonance_min"]
        new_sigs = [s for s in signals if s["code"] not in holding]

        if triggered and new_sigs:
            next_i = day_i + 1
            if next_i >= len(ref) - 5: continue
            sc = sum(1 for p in holding.values() if not p.get("is_base"))
            ms = 6 if cfg["allow_pyramiding"] else 4
            if sc >= ms: continue
            bl = sorted(new_sigs, key=lambda x: x["cp"], reverse=True)[:min(4, ms-sc)]
            tb = cash * 0.8; alloc = tb / max(len(bl), 1)
            for s in bl:
                recs = data_dict.get(s["code"], [])
                if next_i >= len(recs): continue
                op = recs[next_i]["o"]
                if op <= 0: continue
                bp = op*(1+SLIPPAGE); sh = int(alloc/bp/100)*100
                if sh < 100: continue
                cost = sh*bp*(1+COMMISSION)
                if cost > cash: continue
                cash -= cost; holding[s["code"]] = {"shares":sh,"cost":cost,
                    "entry_price":bp,"entry_date":ref[next_i]["date"],
                    "entry_i":next_i,"highest":bp}

        total = cash
        for code, pos in holding.items():
            cc = code.replace("_base",""); recs = data_dict.get(cc, [])
            if day_i < len(recs) and recs[day_i]: total += pos["shares"]*recs[day_i]["c"]
            else: total += pos["shares"]*pos["entry_price"]
        equity.append(total)

    # 清仓
    li = len(ref) - 13
    for code, pos in holding.items():
        cc = code.replace("_base",""); recs = data_dict.get(cc, [])
        sp = recs[li]["c"] if li < len(recs) and recs[li] else pos["entry_price"]
        pr = pos["shares"]*sp*(1-COMMISSION-SLIPPAGE); cash += pr
        trades.append({"profit_pct":round((pr/pos["cost"]-1)*100,2)})
    equity.append(cash)
    return trades, equity


def buy_hold(data_dict):
    recs = data_dict.get("510300", [])
    if len(recs) < 65: return [INITIAL]
    si, ei = 60, len(recs)-13
    sh = int(INITIAL/recs[si]["c"]/100)*100
    return [sh*recs[i]["c"] for i in range(si, ei+1)]


def metrics(equity, trades, name):
    if len(equity) < 2: return {"name":name}
    tr = (equity[-1]/equity[0]-1)*100; ar = ((equity[-1]/equity[0])**(252/max(len(equity),1))-1)*100
    peak=equity[0]; md=0
    alldd = []
    for v in equity:
        dd=(v-peak)/peak*100
        if v>peak: peak=v; dd=0
        if dd<md: md=dd
        alldd.append(dd)
    avg_dd = sum(alldd)/len(alldd) if alldd else 0
    dr=[(equity[i]/equity[i-1]-1) for i in range(1,len(equity))]
    avg_r = sum(dr)/len(dr) if dr else 0
    std_r = (sum((r-avg_r)**2 for r in dr)/len(dr))**0.5 if dr else 0
    sh = (avg_r/std_r*(252**0.5)) if std_r > 0 else 0
    win = [t for t in trades if t["profit_pct"] > 0]
    loss = [t for t in trades if t["profit_pct"] <= 0]
    wr = len(win)/len(trades)*100 if trades else 0
    aw = sum(t["profit_pct"] for t in win)/len(win) if win else 0
    al_val = sum(t["profit_pct"] for t in loss)/len(loss) if loss else 0
    tp = sum(t["profit_pct"] for t in win); tl = abs(sum(t["profit_pct"] for t in loss))
    pf = tp/tl if tl > 0 else float('inf')
    cm = ar/abs(md) if md < 0 else float('inf')
    n_pos_days = sum(1 for v in equity if v > equity[0])
    return {"name":name,"total_return":round(tr,2),"annual_return":round(ar,2),
            "max_drawdown":round(md,2),"avg_drawdown":round(avg_dd,2),
            "sharpe":round(sh,2),"calmar":round(cm,2) if cm!=float('inf') else "∞",
            "n_trades":len(trades),"win_rate":round(wr,1),
            "avg_win":round(aw,2),"avg_loss":round(al_val,2),
            "profit_factor":round(pf,2) if pf!=float('inf') else "∞",
            "days_in_profit":n_pos_days}


def main():
    print("=" * 92)
    print("简化模型 (固定参数, 2趋势) vs 当前复杂模型 (4趋势 + 动态底仓)")
    print("=" * 92)

    print("\n📡 加载15只ETF数据 (800天)...")
    data_dict = {}
    for code in sorted(ETFS):
        records = fetch(code, 800)
        if records:
            data_dict[code] = records
            print(f"  ✅ {code} {ETFS[code]['n'][:12]}: {len(records)}条")
        else:
            print(f"  ❌ {code} 获取失败")

    ref = data_dict["510300"]
    ref_dates = [r["date"] for r in ref]

    periods = [
        ("短期 1年", "2025-05", "2026-05"),
        ("中期 2年", "2024-05", "2026-05"),
        ("长期 3年", "2023-05", "2026-05"),
    ]

    all_results = {}

    for pname, spfx, epfx in periods:
        mask = [i for i, d in enumerate(ref_dates) if d >= spfx and d <= epfx]
        if len(mask) < 70: continue
        si, ei = max(60, mask[0]), min(len(ref)-13, mask[-1])
        if ei - si < 60: continue

        pdata = {}
        for code, recs_list in data_dict.items():
            if si < len(recs_list) and ei < len(recs_list):
                pdata[code] = recs_list[si:ei+1]

        start_d = pdata["510300"][0]["date"]
        end_d = pdata["510300"][-1]["date"]
        days_n = len(pdata["510300"])
        print(f"\n{'='*92}")
        print(f"📅 {pname} ({start_d} ~ {end_d}, {days_n}天)")
        print(f"{'='*92}")

        print("  ⏳ 简化模型...")
        ts, es = backtest(pdata, "simplified")
        ms = metrics(es, ts, "简化模型")

        print("  ⏳ 复杂模型...")
        tc, ec = backtest(pdata, "current")
        mc = metrics(ec, tc, "复杂模型")

        ebh = buy_hold(pdata)
        mbh = metrics(ebh, [], "买持510300")

        all_results[pname] = {"simplified":ms, "current":mc, "bh":mbh}

        excess = ms["total_return"] - mc["total_return"]
        dd_diff = ms["max_drawdown"] - mc["max_drawdown"]
        sh_diff = ms["sharpe"] - mc["sharpe"]

        print(f"\n  {'':>16} {'总收益':>8} {'年化':>8} {'回撤':>8} {'夏普':>6} {'卡玛':>6} {'交易':>5} {'胜率':>6} {'盈亏比':>7}")
        print("  " + "-" * 80)
        for m in [ms, mc, mbh]:
            pf_str = f"{m['profit_factor']:>7}" if isinstance(m.get('profit_factor'), str) else f"{m['profit_factor']:>7.2f}"
            print(f"  {m['name']:>16} {m['total_return']:>+7.1f}% {m['annual_return']:>+7.1f}% "
                  f"{m['max_drawdown']:>+7.1f}% {m['sharpe']:>6.2f} "
                  f"{str(m['calmar']):>6} {m['n_trades']:>5} {m['win_rate']:>5.1f}% {pf_str}")

        print(f"\n  📊 简化 vs 复杂差异:")
        print(f"     收益: {excess:+.1f}% | 回撤: {dd_diff:+.1f}% | 夏普: {sh_diff:+.2f}")
        if excess > 0: print(f"     ✅ 简化版收益更优 ({excess:+.1f}%)")
        else: print(f"     ⚠️ 复杂版收益更优 ({-excess:+.1f}%)")
        if dd_diff > 0: print(f"     ⚠️ 简化版回撤更大 ({dd_diff:+.1f}%)")
        else: print(f"     ✅ 简化版回撤更小 ({dd_diff:+.1f}%)")

    # ============================================================
    # 跨周期汇总
    # ============================================================
    print(f"\n{'='*92}")
    print(f"📊 跨周期汇总")
    print(f"{'='*92}")

    print(f"\n  {'周期':<16} {'简化收益':>8} {'复杂收益':>8} {'超额':>8} "
          f"{'简化回撤':>8} {'复杂回撤':>8} {'回撤改善':>8} {'简化夏普':>7} {'复杂夏普':>7} {'买持':>8}")
    print("  " + "-" * 92)

    total_excess = 0; total_dd_improve = 0; n_p = 0
    for pname in ["短期 1年","中期 2年","长期 3年"]:
        if pname not in all_results: continue
        r = all_results[pname]
        excess = r["simplified"]["total_return"] - r["current"]["total_return"]
        dd_improve = r["simplified"]["max_drawdown"] - r["current"]["max_drawdown"]
        sh_s = r["simplified"]["sharpe"]; sh_c = r["current"]["sharpe"]
        total_excess += excess; total_dd_improve += dd_improve; n_p += 1
        print(f"  {pname:<16} {r['simplified']['total_return']:>+7.1f}% {r['current']['total_return']:>+7.1f}% "
              f"{excess:>+7.1f}% {r['simplified']['max_drawdown']:>+7.1f}% {r['current']['max_drawdown']:>+7.1f}% "
              f"{dd_improve:>+7.1f}% {sh_s:>6.2f}  {sh_c:>6.2f}  {r['bh']['total_return']:>+7.1f}%")

    avg_excess = total_excess/n_p if n_p > 0 else 0
    avg_dd = total_dd_improve/n_p if n_p > 0 else 0

    print(f"\n  📌 简化版平均超额收益: {avg_excess:+.1f}%")
    print(f"  📌 简化版平均回撤改善: {avg_dd:+.1f}%")

    # 交易对比
    print(f"\n  {'周期':<16} {'简化交易':>8} {'复杂交易':>8} {'简化胜率':>8} {'复杂胜率':>8}")
    print("  " + "-" * 58)
    for pname in ["短期 1年","中期 2年","长期 3年"]:
        if pname not in all_results: continue
        r = all_results[pname]
        print(f"  {pname:<16} {r['simplified']['n_trades']:>8} {r['current']['n_trades']:>8} "
              f"{r['simplified']['win_rate']:>7.1f}% {r['current']['win_rate']:>7.1f}%")

    # 3年详细对比
    best3y = all_results.get("长期 3年", {})
    if best3y:
        s = best3y["simplified"]; c = best3y["current"]
        print(f"\n{'='*92}")
        print(f"🔍 3年详细对比:")
        print(f"{'='*92}")
        print(f"  {'':>20} {'简化':>14} {'复杂':>14} {'差':>10}")
        print("  " + "-" * 62)
        for k in ["total_return","annual_return","max_drawdown","sharpe","calmar","n_trades","win_rate","avg_win","avg_loss","profit_factor"]:
            sv = s.get(k, "?"); cv = c.get(k, "?")
            diff = ""
            if isinstance(sv, (int,float)) and isinstance(cv, (int,float)):
                diff = f"{sv-cv:+.2f}"
            print(f"  {k:>20}: {str(sv):>14} {str(cv):>14} {diff:>10}")

    # ============================================================
    # 结论
    # ============================================================
    print(f"\n{'='*92}")
    print(f"📋 结论")
    print(f"{'='*92}")

    if avg_excess > 1.0:
        print(f"  ✅ 简化版收益显著更优 (+{avg_excess:.1f}% 平均超额)")
        print(f"     说明: 复杂模型的参数搜索带来了过拟合, 削弱了样本外表现")
    elif avg_excess > 0:
        print(f"  ✅ 简化版收益略优 (+{avg_excess:.1f}%)")
        print(f"     简化版用更少的参数实现了相当的收益, 稳健性更好")
    elif avg_excess > -1.0:
        print(f"  ⚖️ 两版收益接近 ({avg_excess:.1f}%差异)")
        print(f"     复杂版多出的参数没有带来实质性提升, 属无效复杂度")
    else:
        print(f"  ⚠️ 复杂版收益更优 ({-avg_excess:.1f}%超额)")
        print(f"     但需要警惕: 这可能是在回测期间过拟合的结果")

    if avg_dd > 0:
        print(f"  ⚠️ 简化版回撤更大 (+{avg_dd:.1f}%) — 复杂版的更多防御参数有边际价值")
    else:
        print(f"  ✅ 简化版回撤更小 ({avg_dd:.1f}%) — 复杂版的防御参数未产生实质保护")

    print(f"\n  💡 建议: ", end="")
    if avg_excess > -0.5 and avg_dd < 1.0:
        print("采用简化版 — 同样效果, 更低的过拟合风险, 更易维护")
    elif avg_excess > 1.0:
        print("采用简化版 — 收益显著更好, 复杂模型已明显过拟合")
    else:
        print("保留复杂版但缩小参数空间 — 至少去掉60天滚动权重优化")


if __name__ == "__main__":
    main()
