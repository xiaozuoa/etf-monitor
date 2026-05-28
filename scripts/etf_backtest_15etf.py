#!/usr/bin/env python3
"""15 ETF池优化 — 共振阈值+持有期网格搜索 vs 旧9只"""

import os, sys, io, time, itertools

if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from etf_engine import ETFS
from etf_signals import fetch, detect_trend, calc_rs, compute_cp, COMMISSION, SLIPPAGE, INITIAL

# 旧9只池
OLD_ETFS = {
    "510300": "沪深300华泰","510310":"沪深300易方达","510330":"沪深300华夏",
    "159919":"沪深300嘉实","510050":"上证50","510500":"中证500",
    "512100":"中证1000","588000":"科创50","159915":"创业板",
}

def backtest(data_dict, etf_pool, config):
    """
    config: {regime: {cp_threshold, resonance_min, hold_days, allow_pyramiding}}
    """
    ref = data_dict.get("510300",[])
    if len(ref)<65: return [],[INITIAL]

    cash = INITIAL; holding = {}; equity = [INITIAL]; trades = []
    base_cooldown = 0
    n_etf = len([c for c in data_dict if c in etf_pool])

    for day_i in range(60, len(ref)-12):
        date = ref[day_i]["date"]
        if base_cooldown>0: base_cooldown-=1
        idx_c=ref[day_i]["c"]; idx_chg=(idx_c-ref[day_i-1]["c"])/ref[day_i-1]["c"]*100

        trend = detect_trend(ref, day_i)
        t = trend["trend"]; above = trend["above_ma"]

        # 选配置
        if t=="up": cfg=config["up"]
        elif t=="down": cfg=config["down"]
        elif above: cfg=config.get("neutral_up", config["neutral"])
        else: cfg=config["neutral"]

        # 底仓
        s=trend["strength"]
        if s>=70: min_pct=0.40
        elif s>=50 and t=="up": min_pct=0.25
        elif s>=50: min_pct=0.15
        else: min_pct=0

        total_eq=cash
        for _,pos in holding.items():
            r300=data_dict.get("510300",[])
            if day_i<len(r300) and r300[day_i]: total_eq+=pos["shares"]*r300[day_i]["c"]
            else: total_eq+=pos["shares"]*pos["entry_price"]
        cur_exp=(total_eq-cash)/total_eq if total_eq>0 else 0

        if min_pct>0.15 and len(holding)==0 and cur_exp<0.1 and above and s>55 and not base_cooldown:
            target=min(0.30, min_pct*0.6); next_i=day_i+1
            if next_i<len(ref)-5:
                r300=data_dict.get("510300",[])
                if next_i<len(r300):
                    op=r300[next_i]["o"]
                    if op>0:
                        alloc=cash*target; bp=op*(1+SLIPPAGE); sh=int(alloc/bp/100)*100
                        if sh>=100:
                            cost=sh*bp*(1+COMMISSION)
                            if cost<=cash: cash-=cost; holding["base"]={"shares":sh,"cost":cost,"entry_price":bp,"entry_date":ref[next_i]["date"],"entry_i":next_i,"highest":bp,"is_base":True}

        # 卖出
        to_sell=[]
        for code,pos in holding.items():
            if pos.get("is_base"):
                exit_base=False
                rb=data_dict.get("510300",[]); cur_c=rb[day_i]["c"] if day_i<len(rb) and rb[day_i] else pos["entry_price"]
                if t=="down" and s<40: exit_base=True
                if not above and trend["slope"]<-0.5: exit_base=True
                if (cur_c-pos["entry_price"])/pos["entry_price"]*100<-2.5: exit_base=True
                if exit_base:
                    sp=cur_c; pr=pos["shares"]*sp*(1-COMMISSION-SLIPPAGE); cash+=pr
                    trades.append({"profit_pct":round((pr/pos["cost"]-1)*100,2)})
                    base_cooldown=15; to_sell.append(code)
            else:
                if day_i-pos["entry_i"]>=cfg["hold_days"]:
                    recs=data_dict.get(code,[])
                    sp=recs[day_i]["c"] if day_i<len(recs) and recs[day_i] else pos["entry_price"]
                    pr=pos["shares"]*sp*(1-COMMISSION-SLIPPAGE); cash+=pr
                    trades.append({"profit_pct":round((pr/pos["cost"]-1)*100,2)})
                    to_sell.append(code)
        for code in to_sell: del holding[code]

        # 信号
        signals=[]
        for code,recs in data_dict.items():
            if code not in etf_pool or day_i>=len(recs): continue
            cp,chg,vr,is_c,close=compute_cp(recs,day_i,idx_chg)
            if cp>=cfg["cp_threshold"]: signals.append({"code":code,"cp":cp})

        triggered=len(signals)>=cfg["resonance_min"]
        new_sigs=[s for s in signals if s["code"] not in holding]

        if triggered and new_sigs:
            next_i=day_i+1
            if next_i>=len(ref)-5: continue
            sc=sum(1 for p in holding.values() if not p.get("is_base"))
            ms=6 if cfg["allow_pyramiding"] else 4
            if sc>=ms: continue
            bl=sorted(new_sigs,key=lambda x:x["cp"],reverse=True)[:min(4,ms-sc)]
            tb=cash*0.8; alloc=tb/max(len(bl),1)
            for s in bl:
                recs=data_dict.get(s["code"],[])
                if next_i>=len(recs): continue
                op=recs[next_i]["o"]
                if op<=0: continue
                bp=op*(1+SLIPPAGE); sh=int(alloc/bp/100)*100
                if sh<100: continue
                cost=sh*bp*(1+COMMISSION)
                if cost>cash: continue
                cash-=cost; holding[s["code"]]={"shares":sh,"cost":cost,"entry_price":bp,"entry_date":ref[next_i]["date"],"entry_i":next_i,"highest":bp}

        total=cash
        for code,pos in holding.items():
            cc=code.replace("_base",""); recs=data_dict.get(cc,[])
            if day_i<len(recs) and recs[day_i]: total+=pos["shares"]*recs[day_i]["c"]
            else: total+=pos["shares"]*pos["entry_price"]
        equity.append(total)

    li=len(ref)-13
    for code,pos in holding.items():
        cc=code.replace("_base",""); recs=data_dict.get(cc,[])
        sp=recs[li]["c"] if li<len(recs) and recs[li] else pos["entry_price"]
        pr=pos["shares"]*sp*(1-COMMISSION-SLIPPAGE); cash+=pr
        trades.append({"profit_pct":round((pr/pos["cost"]-1)*100,2)})
    equity.append(cash)
    return trades,equity

def metrics(equity, trades):
    if len(equity)<2: return 0,0,0
    tr=(equity[-1]/equity[0]-1)*100
    ar=((equity[-1]/equity[0])**(252/max(len(equity),1))-1)*100
    peak=equity[0]; md=0
    for v in equity:
        dd=(v-peak)/peak*100
        if v>peak: peak=v; dd=0
        if dd<md: md=dd
    dr=[(equity[i]/equity[i-1]-1) for i in range(1,len(equity))]
    sh=(sum(dr)/len(dr)/((sum((r-sum(dr)/len(dr))**2 for r in dr)/len(dr))**0.5)*(252**0.5)) if dr else 0
    return round(tr,2),round(md,2),round(sh,2),round(ar,2)

def buy_hold(data_dict):
    recs=data_dict.get("510300",[])
    if len(recs)<65: return [INITIAL]
    si,ei=60,len(recs)-13; sh=int(INITIAL/recs[si]["c"]/100)*100
    return [sh*recs[i]["c"] for i in range(si,ei+1)]

def main():
    print("="*80)
    print("15 ETF池 — 共振阈值+持有期 联合优化")
    print("="*80)

    # 加载15只
    print("\nLoading 15 ETFs...")
    data_dict={}
    for code in ETFS:
        data_dict[code]=fetch(code,800)
        print(f"  {code} {ETFS[code]['n']}: {len(data_dict[code])}d", end="")
    print()

    # 旧9只数据
    old_data={c:data_dict[c] for c in OLD_ETFS if c in data_dict}

    ref=data_dict["510300"]; ref_dates=[r["date"] for r in ref]
    mask=[i for i,d in enumerate(ref_dates) if d>="2023-05"]
    si,ei=max(60,mask[0]),min(len(ref)-13,len(ref_dates)-1)

    # 切分窗口
    def slice_data(raw, si, ei):
        return {c:[r for r in raw[c][si:ei+1]] for c in raw if si<len(raw[c]) and ei<len(raw[c])}

    precs_new = slice_data(data_dict, si, ei)
    precs_old = slice_data(old_data, si, ei)
    print(f"\nWindow: {precs_new['510300'][0]['date']} ~ {precs_new['510300'][-1]['date']}")

    # 旧9只基线
    old_config = {
        "up":{"cp_threshold":45,"resonance_min":2,"hold_days":10,"allow_pyramiding":True},
        "neutral_up":{"cp_threshold":50,"resonance_min":2,"hold_days":7,"allow_pyramiding":False},
        "neutral":{"cp_threshold":50,"resonance_min":3,"hold_days":4,"allow_pyramiding":False},
        "down":{"cp_threshold":50,"resonance_min":3,"hold_days":3,"allow_pyramiding":False},
    }
    _,e_old = backtest(precs_old, OLD_ETFS, old_config)
    tr_old,md_old,sh_old,ar_old = metrics(e_old,[])
    ebh=buy_hold(precs_new); tr_bh,md_bh,sh_bh,ar_bh=metrics(ebh,[])
    print(f"\n  旧9只基线: +{tr_old:.1f}% DD{md_old:.1f}% SH{sh_old:.2f}")
    print(f"  买持:       +{tr_bh:.1f}% DD{md_bh:.1f}% SH{sh_bh:.2f}")

    # 15只联合优化
    print(f"\n  15只网格搜索 (resonance×hold_days)...")
    # 参数范围
    res_up_range   = [2,3]          # 上升: 共振数
    res_nu_range   = [2,3,4]        # 中性偏多
    res_n_range    = [3,4,5]        # 中性
    res_dn_range   = [3,4,5]        # 下降
    hold_up_range  = [8,10,12,15]   # 上升持有天
    hold_nu_range  = [5,7,10]       # 中性偏多
    hold_n_range   = [3,4,5]        # 中性
    hold_dn_range  = [2,3,4]        # 下降

    best_score=-999; best_cfg=None; best_tr=0
    results=[]; n=0

    for ru in res_up_range:
     for rn2 in res_nu_range:
      for rn in res_n_range:
       for rd in res_dn_range:
        for hu in hold_up_range:
         for hn2 in hold_nu_range:
          for hn in hold_n_range:
           for hd in hold_dn_range:
            if ru>rn2 or rn2>rn: continue  # 单调性约束
            n+=1
            cfg={
                "up":{"cp_threshold":45,"resonance_min":ru,"hold_days":hu,"allow_pyramiding":True},
                "neutral_up":{"cp_threshold":50,"resonance_min":rn2,"hold_days":hn2,"allow_pyramiding":False},
                "neutral":{"cp_threshold":50,"resonance_min":rn,"hold_days":hn,"allow_pyramiding":False},
                "down":{"cp_threshold":50,"resonance_min":rd,"hold_days":hd,"allow_pyramiding":False},
            }
            _,eq=backtest(precs_new, ETFS, cfg)
            tr,md,sh,ar=metrics(eq,[])
            score=tr*0.5+sh*15-abs(md)*0.2
            results.append((tr,md,sh,cfg,score))
            if score>best_score: best_score=score; best_cfg=cfg; best_tr=tr

    print(f"  测试{len(results)}种组合\n")

    results.sort(key=lambda x:x[4], reverse=True)
    print(f"{'Rank':<5} {'Config (R_up/Nu/N/Dn + Hold)':<40} {'Ret':>8} {'DD':>6} {'SH':>5} {'Score':>7}")
    print("-"*75)
    for rank,(tr,md,sh,cfg,score) in enumerate(results[:10],1):
        desc=f"R{cfg['up']['resonance_min']}/{cfg['neutral_up']['resonance_min']}/{cfg['neutral']['resonance_min']}/{cfg['down']['resonance_min']} H{cfg['up']['hold_days']}/{cfg['neutral_up']['hold_days']}/{cfg['neutral']['hold_days']}/{cfg['down']['hold_days']}"
        marker=" <--" if rank==1 else ""
        print(f"{rank:<5} {desc:<40} {tr:>+7.1f}% {md:>+5.1f}% {sh:>5.2f} {score:>7.1f}{marker}")

    # 最优 vs 旧 vs 买持
    _,e_best=backtest(precs_new, ETFS, best_cfg)
    tr_best,md_best,sh_best,ar_best=metrics(e_best,[])
    print(f"\n  旧9只:     +{tr_old:.1f}% DD{md_old:.1f}% SH{sh_old:.2f}")
    print(f"  15只最优:  +{tr_best:.1f}% DD{md_best:.1f}% SH{sh_best:.2f}")
    print(f"  买持:      +{tr_bh:.1f}% DD{md_bh:.1f}% SH{sh_bh:.2f}")
    print(f"\n  15只 vs 旧9只: {tr_best-tr_old:+.1f}%")
    print(f"  15只 vs 买持:  {tr_best-tr_bh:+.1f}%")

    # 最优参数
    print(f"\n  最优参数:")
    for k in ["up","neutral_up","neutral","down"]:
        c=best_cfg[k]
        print(f"    {k}: R={c['resonance_min']} H={c['hold_days']}d CP>={c['cp_threshold']}% pyr={c['allow_pyramiding']}")

if __name__=="__main__":
    main()
