#!/usr/bin/env python3
"""Walk-Forward验证: 网格搜索参数 → 样本外测试 → 对比简化模型"""

import os, sys, io, json, urllib.request, ssl, itertools, copy
from collections import defaultdict

if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from etf_engine import ETFS

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False; SSL_CTX.verify_mode = ssl.CERT_NONE
COMMISSION = 0.00025; SLIPPAGE = 0.0005; INITIAL = 100000


def fetch(code, limit=800):
    pfx = "sh" if code.startswith(("51","56","0")) else "sz"
    if code.startswith("sh") or code.startswith("sz"): pfx2, nc = code[:2], code[2:]
    else: pfx2, nc = pfx, code
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={pfx2}{nc},day,,,{limit},qfq"
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as r:
        d = json.loads(r.read().decode("utf-8"))
    k = d.get("data",{}).get(f"{pfx2}{nc}",{}).get("qfqday",[]) or d.get("data",{}).get(f"{pfx2}{nc}",{}).get("day",[])
    return [{"date":r[0],"o":float(r[1]),"c":float(r[2]),"h":float(r[3]),"l":float(r[4]),"v":float(r[5])}
            for r in k if len(r)>=6 and r[0]]


def detect_trend(ref, day_i):
    if day_i < 50: return {"trend":"neutral","slope":0,"strength":50,"above_ma":True}
    closes = [d["c"] for d in ref[day_i-49:day_i+1]]
    ma_now = sum(closes)/len(closes)
    ma_10d = sum(closes[:10])/10
    slope = (ma_now-ma_10d)/ma_10d*100 if ma_10d>0 else 0
    above = ref[day_i]["c"] > ma_now
    if slope > 1.0 and above: t = "up"
    elif slope < -1.0 and not above: t = "down"
    else: t = "neutral"
    s = min(100, 50+slope*15) if t!="neutral" else 50
    return {"trend":t,"slope":round(slope,2),"strength":round(s,1),"above_ma":above}


def calc_rs(etf_chg, idx_chg, vol_ratio):
    excess = etf_chg-idx_chg; score, is_c = 0, False
    if idx_chg < -0.5 and etf_chg > idx_chg+0.3: score += 40; is_c = True
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
    v_raw = min(1, max(0, (vr-0.7)/1.3)) if vr >= 0.7 else 0
    rs, is_c = calc_rs(chg, idx_chg, vr); d_raw = rs/100
    return (v_raw*0.55 + d_raw*0.40 + 0.12*0.05)*100, chg, vr, is_c, c


def get_params_from_trend(trend, cfg):
    """从配置中提取当前趋势对应的参数"""
    t = trend["trend"]
    if t == "up":
        return cfg["up"]
    else:
        return cfg["other"]


def backtest_one(data_dict, cfg_params):
    """单次回测, 返回 (trades, equity, metrics_dict)"""
    ref = data_dict.get("510300", [])
    if len(ref) < 55: return [], [INITIAL], {}

    cash = INITIAL; holding = {}; equity = [INITIAL]; trades = []

    for day_i in range(50, len(ref) - 12):
        idx_c = ref[day_i]["c"]
        idx_chg = (idx_c-ref[day_i-1]["c"])/ref[day_i-1]["c"]*100
        trend = detect_trend(ref, day_i)
        p = get_params_from_trend(trend, cfg_params)

        # --- 卖出 ---
        to_sell = []
        for code, pos in holding.items():
            if day_i - pos["entry_i"] >= p["hold_days"]:
                recs = data_dict.get(code, [])
                sp = recs[day_i]["c"] if day_i < len(recs) and recs[day_i] else pos["entry_price"]
                pr = pos["shares"]*sp*(1-COMMISSION-SLIPPAGE); cash += pr
                trades.append({"profit_pct":round((pr/pos["cost"]-1)*100,2)})
                to_sell.append(code)
        for code in to_sell: del holding[code]

        # --- 信号 ---
        signals = []
        for code, recs in data_dict.items():
            if code not in ETFS or day_i >= len(recs): continue
            cp, chg, vr, is_c, close = compute_cp(recs, day_i, idx_chg)
            if cp >= p["cp_threshold"]:
                signals.append({"code":code,"cp":cp})

        triggered = len(signals) >= p["resonance_min"]
        new_sigs = [s for s in signals if s["code"] not in holding]

        if triggered and new_sigs:
            next_i = day_i + 1
            if next_i >= len(ref) - 5: continue
            sc = sum(1 for pos in holding.values())
            ms = 6 if p["allow_pyramiding"] else 4
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
            recs = data_dict.get(code, [])
            if day_i < len(recs) and recs[day_i]: total += pos["shares"]*recs[day_i]["c"]
            else: total += pos["shares"]*pos["entry_price"]
        equity.append(total)

    li = len(ref) - 13
    for code, pos in holding.items():
        recs = data_dict.get(code, [])
        sp = recs[li]["c"] if li < len(recs) and recs[li] else pos["entry_price"]
        pr = pos["shares"]*sp*(1-COMMISSION-SLIPPAGE); cash += pr
        trades.append({"profit_pct":round((pr/pos["cost"]-1)*100,2)})
    equity.append(cash)

    m = _metrics(equity, trades)
    return trades, equity, m


def _metrics(equity, trades):
    if len(equity) < 2: return {"total_return":0,"max_drawdown":0,"sharpe":0,"n_trades":0}
    tr = (equity[-1]/equity[0]-1)*100
    ar = ((equity[-1]/equity[0])**(252/max(len(equity),1))-1)*100
    peak=equity[0]; md=0
    for v in equity:
        dd=(v-peak)/peak*100
        if v>peak: peak=v; dd=0
        if dd<md: md=dd
    dr=[(equity[i]/equity[i-1]-1) for i in range(1,len(equity))]
    avg_r = sum(dr)/len(dr) if dr else 0
    std_r = (sum((r-avg_r)**2 for r in dr)/len(dr))**0.5 if dr else 0
    sh = (avg_r/std_r*(252**0.5)) if std_r > 0 else 0
    win = [t for t in trades if t["profit_pct"] > 0]
    loss = [t for t in trades if t["profit_pct"] <= 0]
    wr = len(win)/len(trades)*100 if trades else 0
    aw = sum(t["profit_pct"] for t in win)/len(win) if win else 0
    al_val = sum(t["profit_pct"] for t in loss)/len(loss) if loss else 0
    return {"total_return":round(tr,2),"annual_return":round(ar,2),
            "max_drawdown":round(md,2),"sharpe":round(sh,2),
            "n_trades":len(trades),"win_rate":round(wr,1),
            "avg_win":round(aw,2),"avg_loss":round(al_val,2)}


# ============================================================
# 参数空间
# ============================================================

UP_PARAMS = list(itertools.product(
    [45, 50],          # cp_threshold
    [2, 3],             # resonance_min
    [5, 7, 10],         # hold_days
    [True, False],      # allow_pyramiding
))

OTHER_PARAMS = list(itertools.product(
    [45, 50],           # cp_threshold
    [2, 3, 4],          # resonance_min
    [4, 5, 7],          # hold_days
    [False],            # allow_pyramiding (保守)
))

SIMPLIFIED_CFG = {
    "up": {"cp_threshold":50,"resonance_min":2,"hold_days":7,"allow_pyramiding":True},
    "other": {"cp_threshold":50,"resonance_min":3,"hold_days":5,"allow_pyramiding":False},
}


def grid_search_best(data_dict):
    """在训练数据上搜索最优参数组合, 返回 (best_config, best_score, all_results)"""
    best_score = -999
    best_cfg = copy.deepcopy(SIMPLIFIED_CFG)

    total = len(UP_PARAMS) * len(OTHER_PARAMS)
    checked = 0

    for up_p in UP_PARAMS:
        up_cfg = {"cp_threshold":up_p[0],"resonance_min":up_p[1],
                  "hold_days":up_p[2],"allow_pyramiding":up_p[3]}
        for ot_p in OTHER_PARAMS:
            ot_cfg = {"cp_threshold":ot_p[0],"resonance_min":ot_p[1],
                      "hold_days":ot_p[2],"allow_pyramiding":ot_p[3]}
            cfg = {"up":up_cfg, "other":ot_cfg}
            _, _, m = backtest_one(data_dict, cfg)
            checked += 1

            tr = m.get("total_return", 0)
            dd = m.get("max_drawdown", -100)
            sh = m.get("sharpe", 0)
            nt = m.get("n_trades", 0)

            if nt < 5:
                continue  # 信号太少, 不可靠

            # 综合评分: 收益主导 + 回撤惩罚 + 夏普加权 + 交易数保底
            score = tr * 1.0 + dd * 0.5 + sh * 10.0 + min(nt, 30) * 0.1

            if score > best_score:
                best_score = score
                best_cfg = cfg

    return best_cfg, best_score


# ============================================================
# Walk-Forward 窗口
# ============================================================

# 训练窗口 ~12个月, 测试窗口 ~6个月
WINDOWS = [
    {"name":"W1","train_start":"2023-05-01","train_end":"2024-04-30",
                  "test_start":"2024-05-01","test_end":"2024-10-31"},
    {"name":"W2","train_start":"2023-05-01","train_end":"2024-10-31",
                  "test_start":"2024-11-01","test_end":"2025-04-30"},
    {"name":"W3","train_start":"2023-05-01","train_end":"2025-04-30",
                  "test_start":"2025-05-01","test_end":"2025-10-31"},
    {"name":"W4","train_start":"2023-05-01","train_end":"2025-10-31",
                  "test_start":"2025-11-01","test_end":"2026-05-27"},
]


def slice_data(data_dict, start_date, end_date):
    """按日期切片数据"""
    ref = data_dict.get("510300", [])
    ref_dates = [r["date"] for r in ref]
    mask = [i for i, d in enumerate(ref_dates) if start_date <= d <= end_date]
    if len(mask) < 60: return None
    si, ei = max(50, mask[0]), min(len(ref)-13, mask[-1])
    if ei - si < 50: return None
    result = {}
    for code, recs in data_dict.items():
        if si < len(recs) and ei < len(recs):
            result[code] = recs[si:ei+1]
    return result


def main():
    print("=" * 94)
    print("Walk-Forward 验证: 训练期网格搜索 → 样本外测试")
    print("=" * 94)

    # 加载数据
    print("\n📡 加载15只ETF...")
    data_dict = {}
    for code in sorted(ETFS):
        records = fetch(code, 800)
        if records:
            data_dict[code] = records
    ref = data_dict["510300"]
    print(f"  沪深300: {ref[0]['date']} ~ {ref[-1]['date']} ({len(ref)}条)")

    all_test_results_wf = []
    all_test_results_simple = []
    search_history = []

    for w in WINDOWS:
        print(f"\n{'─'*70}")
        print(f"🔍 {w['name']}: 训练 [{w['train_start']} ~ {w['train_end']}] → 测试 [{w['test_start']} ~ {w['test_end']}]")
        print(f"{'─'*70}")

        train_data = slice_data(data_dict, w["train_start"], w["train_end"])
        test_data = slice_data(data_dict, w["test_start"], w["test_end"])

        if not train_data or not test_data:
            print(f"  ⚠️ 数据不足, 跳过")
            continue

        td = test_data["510300"]
        print(f"  训练: {train_data['510300'][0]['date']}~{train_data['510300'][-1]['date']} ({len(train_data['510300'])}天)")
        print(f"  测试: {td[0]['date']}~{td[-1]['date']} ({len(td)}天)")

        # 网格搜索
        print(f"  🔧 网格搜索 ({len(UP_PARAMS)}×{len(OTHER_PARAMS)}={len(UP_PARAMS)*len(OTHER_PARAMS)}组合)...")
        best_cfg, best_score = grid_search_best(train_data)

        # 记录搜索结果
        search_history.append({
            "window": w["name"],
            "best_cfg": best_cfg,
            "score": round(best_score, 1),
        })
        print(f"  ✅ 最优: UP(cp≥{best_cfg['up']['cp_threshold']},≥{best_cfg['up']['resonance_min']}只,持{best_cfg['up']['hold_days']}天,叠{'Y' if best_cfg['up']['allow_pyramiding'] else 'N'}) | "
              f"OTHER(cp≥{best_cfg['other']['cp_threshold']},≥{best_cfg['other']['resonance_min']}只,持{best_cfg['other']['hold_days']}天)")

        # 样本外测试 — 网格搜索版
        _, _, m_wf = backtest_one(test_data, best_cfg)
        all_test_results_wf.append(m_wf)
        print(f"  📊 网格搜索版 (样本外): Ret={m_wf['total_return']:+.1f}% DD={m_wf['max_drawdown']:+.1f}% SH={m_wf['sharpe']:.2f} Tr={m_wf['n_trades']}")

        # 样本外测试 — 简化版 (同样本外期间)
        _, _, m_simple = backtest_one(test_data, SIMPLIFIED_CFG)
        all_test_results_simple.append(m_simple)
        print(f"  📊 简化固定版 (样本外): Ret={m_simple['total_return']:+.1f}% DD={m_simple['max_drawdown']:+.1f}% SH={m_simple['sharpe']:.2f} Tr={m_simple['n_trades']}")

        excess = m_wf["total_return"] - m_simple["total_return"]
        dd_diff = m_wf["max_drawdown"] - m_simple["max_drawdown"]
        print(f"  📈 网格搜索超额: {excess:+.1f}% | 回撤差: {dd_diff:+.1f}%")

    # ============================================================
    # 汇总: 合并所有测试期
    # ============================================================
    print(f"\n{'='*94}")
    print(f"📊 Walk-Forward 汇总 — 样本外表现")
    print(f"{'='*94}")

    print(f"\n  {'窗口':<6} {'网格版收益':>10} {'简化版收益':>10} {'超额':>8} "
          f"{'网格回撤':>8} {'简化回撤':>8} {'网格夏普':>7} {'简化夏普':>7} "
          f"{'网格交易':>7} {'简化交易':>7}")
    print("  " + "-" * 94)

    total_wf_ret = 0; total_simple_ret = 0; wf_trades = 0; simple_trades = 0
    for i, w in enumerate(WINDOWS):
        if i >= len(all_test_results_wf): continue
        mw = all_test_results_wf[i]; ms = all_test_results_simple[i]
        excess = mw["total_return"] - ms["total_return"]
        dd_diff = mw["max_drawdown"] - ms["max_drawdown"]
        total_wf_ret += mw["total_return"]; total_simple_ret += ms["total_return"]
        wf_trades += mw["n_trades"]; simple_trades += ms["n_trades"]

        emoji = "✅" if excess > 0 else ("⚠️" if excess > -3 else "❌")
        print(f"  {w['name']:<6} {mw['total_return']:>+9.1f}% {ms['total_return']:>+9.1f}% "
              f"{emoji}{excess:>+7.1f}% {mw['max_drawdown']:>+7.1f}% {ms['max_drawdown']:>+7.1f}% "
              f"{mw['sharpe']:>7.2f} {ms['sharpe']:>7.2f} {mw['n_trades']:>7} {ms['n_trades']:>7}")

    avg_excess = total_wf_ret/len(all_test_results_wf) - total_simple_ret/len(all_test_results_simple) if all_test_results_wf else 0
    print(f"\n  📌 网格搜索版 样本外平均收益: {total_wf_ret/len(all_test_results_wf):+.1f}%" if all_test_results_wf else "")
    print(f"  📌 简化固定版 样本外平均收益: {total_simple_ret/len(all_test_results_simple):+.1f}%" if all_test_results_simple else "")
    print(f"  📌 平均超额: {avg_excess:+.1f}%")
    print(f"  📌 网格搜索版总交易: {wf_trades} | 简化版总交易: {simple_trades}")

    # ============================================================
    # 参数稳定性分析
    # ============================================================
    print(f"\n{'='*94}")
    print(f"🔍 参数稳定性 — 各窗口搜到的最优参数")
    print(f"{'='*94}")

    print(f"\n  {'窗口':<6} {'UP_cp':>6} {'UP_res':>7} {'UP_hold':>8} {'UP_pyr':>7} | {'OT_cp':>6} {'OT_res':>7} {'OT_hold':>8}")
    print("  " + "-" * 70)
    for sh in search_history:
        cfg = sh["best_cfg"]
        u = cfg["up"]; o = cfg["other"]
        print(f"  {sh['window']:<6} {u['cp_threshold']:>6} {u['resonance_min']:>7} {u['hold_days']:>8} "
              f"{str(u['allow_pyramiding']):>7} | {o['cp_threshold']:>6} {o['resonance_min']:>7} {o['hold_days']:>8}")

    # 检查参数是否稳定
    up_cps = set(); up_ress = set(); up_holds = set()
    ot_cps = set(); ot_ress = set(); ot_holds = set()
    for sh in search_history:
        cfg = sh["best_cfg"]
        up_cps.add(cfg["up"]["cp_threshold"])
        up_ress.add(cfg["up"]["resonance_min"])
        up_holds.add(cfg["up"]["hold_days"])
        ot_cps.add(cfg["other"]["cp_threshold"])
        ot_ress.add(cfg["other"]["resonance_min"])
        ot_holds.add(cfg["other"]["hold_days"])

    print(f"\n  参数稳定性:")
    print(f"    UP cp_threshold: {sorted(up_cps)} (唯一值={len(up_cps)}) {'✅ 稳定' if len(up_cps)==1 else '⚠️ 不稳定'}")
    print(f"    UP resonance_min: {sorted(up_ress)} (唯一值={len(up_ress)}) {'✅ 稳定' if len(up_ress)==1 else '⚠️ 不稳定'}")
    print(f"    UP hold_days: {sorted(up_holds)} (唯一值={len(up_holds)}) {'✅ 稳定' if len(up_holds)<=2 else '⚠️ 不稳定'}")
    print(f"    OTHER cp_threshold: {sorted(ot_cps)} (唯一值={len(ot_cps)}) {'✅ 稳定' if len(ot_cps)==1 else '⚠️ 不稳定'}")
    print(f"    OTHER resonance_min: {sorted(ot_ress)} (唯一值={len(ot_ress)}) {'✅ 稳定' if len(ot_ress)==1 else '⚠️ 不稳定'}")
    print(f"    OTHER hold_days: {sorted(ot_holds)} (唯一值={len(ot_holds)}) {'✅ 稳定' if len(ot_holds)<=2 else '⚠️ 不稳定'}")

    stable_count = sum(1 for x in [len(up_cps),len(up_ress),len(ot_cps),len(ot_ress)] if x==1) + sum(1 for x in [len(up_holds),len(ot_holds)] if x<=2)
    print(f"\n  稳定性评分: {stable_count}/6 参数在窗口间稳定")

    # ============================================================
    # 结论
    # ============================================================
    print(f"\n{'='*94}")
    print(f"📋 Walk-Forward 结论")
    print(f"{'='*94}")

    if avg_excess > 3:
        print(f"  ✅ 网格搜索在样本外仍有效 (+{avg_excess:.1f}%平均超额)")
        print(f"     参数搜索捕捉到了真实的市场结构变化, 不仅仅是过拟合")
        print(f"     → 建议: 保留网格搜索, 但需限制参数变化范围")
    elif avg_excess > 0:
        print(f"  ⚖️ 网格搜索有微弱的样本外改善 (+{avg_excess:.1f}%)")
        print(f"     改善幅度小, 考虑到复杂度和过拟合风险, 边际价值有限")
        print(f"     → 建议: 可以保留, 但降低重新搜索频率(例如月度而非每日)")
    elif avg_excess > -3:
        print(f"  ⚠️ 网格搜索基本无效 ({avg_excess:.1f}%)")
        print(f"     训练期搜到的参数在样本外没有优势")
        print(f"     → 建议: 去掉网格搜索, 使用固定参数")
    else:
        print(f"  ❌ 网格搜索在样本外表现更差 ({avg_excess:.1f}%)")
        print(f"     这是典型的过拟合: 训练期搜出的参数反而在样本外无效")
        print(f"     → 强烈建议: 立即去掉60天滚动权重优化和参数网格搜索")

    if stable_count >= 5:
        print(f"\n  🔒 参数高度稳定 → 不需要频繁搜索, 改为季度/年度确认即可")
    elif stable_count >= 3:
        print(f"\n  🔓 参数部分稳定 → 可以保留搜索但降低频率")
    else:
        print(f"\n  🔄 参数不稳定 → 说明搜索本身在追噪声, 建议固定参数")


if __name__ == "__main__":
    main()
