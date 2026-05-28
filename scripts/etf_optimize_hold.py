#!/usr/bin/env python3
"""持有期网格优化 — 每种趋势独立寻最优天数"""

import os, sys, io, itertools

if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from etf_engine import ETFS
from etf_signals import fetch, detect_trend, calc_rs, compute_cp, COMMISSION, SLIPPAGE, INITIAL


def detect_trend_at(ref, day_i):
    return detect_trend(ref, day_i)

def get_dynamic_v5(trend):


def backtest_v5_hold(data_dict, hold_days_map):
    """v5策略, 使用给定的持有期映射 {regime: days}"""
    ref=data_dict.get("510300",[])
    if len(ref)<65: return [],[INITIAL]

    cash=INITIAL; holding={}; equity=[INITIAL]; trades=[]
    base_cooldown=0

    for day_i in range(60, len(ref)-12):
        date=ref[day_i]["date"]
        if base_cooldown>0: base_cooldown-=1
        idx_c=ref[day_i]["c"]
        idx_chg=(idx_c-ref[day_i-1]["c"])/ref[day_i-1]["c"]*100

        trend=detect_trend_at(ref,day_i)
        dynamic=get_dynamic_v5(trend)
        dynamic["hold_days"]=hold_days_map.get(dynamic["regime"], 3)
        dynamic["label"]=dynamic["regime"]

        # 底仓(v5逻辑)
        s=trend["strength"]; t=trend["trend"]
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

        if min_pct>0.15 and len(holding)==0 and cur_exp<0.1 and trend["above_ma"] and trend["strength"]>55 and not base_cooldown:
            target_base=min(0.30, min_pct*0.6)
            next_i=day_i+1
            if next_i<len(ref)-5:
                r300=data_dict.get("510300",[])
                if next_i<len(r300):
                    op=r300[next_i]["o"]
                    if op>0:
                        alloc=cash*target_base; bp=op*(1+SLIPPAGE); sh=int(alloc/bp/100)*100
                        if sh>=100:
                            cost=sh*bp*(1+COMMISSION)
                            if cost<=cash: cash-=cost; holding["base"]={"shares":sh,"cost":cost,"entry_price":bp,"entry_date":ref[next_i]["date"],"entry_i":next_i,"highest":bp,"is_base":True}

        # 卖出
        to_sell=[]
        for code,pos in holding.items():
            if pos.get("is_base"):
                exit_base=False
                rb=data_dict.get("510300",[])
                cur_c=rb[day_i]["c"] if day_i<len(rb) and rb[day_i] else pos["entry_price"]
                if trend["trend"]=="down" and trend["strength"]<40: exit_base=True
                if not trend["above_ma"] and trend["slope"]<-0.5: exit_base=True
                if (cur_c-pos["entry_price"])/pos["entry_price"]*100<-2.5: exit_base=True
                if exit_base:
                    sp=cur_c; pr=pos["shares"]*sp*(1-COMMISSION-SLIPPAGE); cash+=pr
                    trades.append({"profit_pct":round((pr/pos["cost"]-1)*100,2)})
                    base_cooldown=15; to_sell.append(code)
            else:
                if day_i-pos["entry_i"]>=dynamic["hold_days"]:
                    recs=data_dict.get(code,[])
                    sp=recs[day_i]["c"] if day_i<len(recs) and recs[day_i] else pos["entry_price"]
                    pr=pos["shares"]*sp*(1-COMMISSION-SLIPPAGE); cash+=pr
                    trades.append({"profit_pct":round((pr/pos["cost"]-1)*100,2)})
                    to_sell.append(code)
        for code in to_sell: del holding[code]

        # 信号
        signals=[]
        for code,recs in data_dict.items():
            if code not in ETFS or day_i>=len(recs): continue
            cp,chg,vr,is_c,close=compute_cp(recs,day_i,idx_chg)
            if cp>=dynamic["cp_threshold"]: signals.append({"code":code,"cp":cp})

        triggered=len(signals)>=dynamic["resonance_min"]
        new_sigs=[s for s in signals if s["code"] not in holding]

        if triggered and new_sigs:
            next_i=day_i+1
            if next_i>=len(ref)-5: continue
            sc=sum(1 for p in holding.values() if not p.get("is_base"))
            ms=5 if dynamic["allow_pyramiding"] else 3
            if sc>=ms: continue
            bl=sorted(new_sigs,key=lambda x:x["cp"],reverse=True)[:min(3,ms-sc)]
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
    md=0; peak=equity[0]
    for v in equity:
        dd=(v-peak)/peak*100
        if v>peak: peak=v; dd=0
        if dd<md: md=dd
    dr=[(equity[i]/equity[i-1]-1) for i in range(1,len(equity))]
    sh=(sum(dr)/len(dr)/((sum((r-sum(dr)/len(dr))**2 for r in dr)/len(dr))**0.5)*(252**0.5)) if dr else 0
    return round(tr,2), round(md,2), round(sh,2)


def main():
    print("="*70)
    print("🔧 v5持有期网格优化")
    print("="*70)

    print("\n📡 加载9只ETF...")
    data_dict={}
    for code in ETFS:
        data_dict[code]=fetch(code,800)
        print(f"  {code}: {len(data_dict[code])}天", end="")
    print()

    ref=data_dict["510300"]; ref_dates=[r["date"] for r in ref]

    # 3年回测窗口
    mask=[i for i,d in enumerate(ref_dates) if d>="2023-05"]
    si,ei=max(60,mask[0]),min(len(ref)-13,len(ref_dates)-1)
    precs={}
    for code in ETFS:
        if code in data_dict:
            recs=data_dict[code]
            if si<len(recs) and ei<len(recs):
                precs[code]=recs[si:ei+1]

    print(f"\n  回测窗口: {precs['510300'][0]['date']} ~ {precs['510300'][-1]['date']}")

    # 基线: v5默认
    base_map={"up":6,"neutral_up":4,"neutral_down":3,"down":3}
    _,eb=backtest_v5_hold(precs,base_map)
    trb,mdb,shb=metrics(eb,[])
    print(f"\n  基线 (6/4/3/3): 收益{trb:+.1f}% 回撤{mdb:.1f}% 夏普{shb:.2f}")

    # 网格搜索
    up_range=[4,5,6,7,8,10]
    nu_range=[2,3,4,5,6,7]
    nd_range=[2,3,4,5]
    dn_range=[2,3,4,5]

    best_score=-999
    best_map=None
    best_tr=0
    results=[]

    total=len(up_range)*len(nu_range)*len(nd_range)*len(dn_range)
    n=0

    for up_d in up_range:
        for nu_d in nu_range:
            for nd_d in nd_range:
                for dn_d in dn_range:
                    n+=1
                    hold_map={"up":up_d,"neutral_up":nu_d,"neutral_down":nd_d,"down":dn_d}
                    _,eq=backtest_v5_hold(precs,hold_map)
                    tr,md,sh=metrics(eq,[])
                    # 综合评分: 收益*0.5 + 夏普*20 - |回撤|*0.3
                    score=tr*0.5+sh*20-abs(md)*0.3
                    results.append((tr,md,sh,hold_map,score))
                    if score>best_score:
                        best_score=score; best_map=hold_map; best_tr=tr

    print(f"  已测试 {n} 种组合")

    # 排序输出 Top 10
    results.sort(key=lambda x: x[4], reverse=True)

    print(f"\n{'排名':<5} {'持有期(上/中偏多/中偏空/下)':<28} {'收益':>8} {'回撤':>7} {'夏普':>6} {'得分':>7}")
    print("-"*70)
    for rank,(tr,md,sh,hm,score) in enumerate(results[:10],1):
        hold_str=f"{hm['up']}/{hm['neutral_up']}/{hm['neutral_down']}/{hm['down']}"
        marker=" ← 最优" if rank==1 else ""
        print(f"{rank:<5} {hold_str:<28} {tr:>+7.1f}% {md:>+6.1f}% {sh:>6.2f} {score:>7.1f}{marker}")

    # 对比基线
    print(f"\n  基线(6/4/3/3): 收益{trb:+.1f}% 回撤{mdb:.1f}% 夏普{shb:.2f}")
    if best_map:
        _,eb2=backtest_v5_hold(precs,best_map)
        trb2,mdb2,shb2=metrics(eb2,[])
        imp=trb2-trb
        print(f"  最优({best_map['up']}/{best_map['neutral_up']}/{best_map['neutral_down']}/{best_map['down']}): 收益{trb2:+.1f}% 回撤{mdb2:.1f}% 夏普{shb2:.2f}")
        print(f"  改进: 收益{imp:+.1f}%")

    # v4a对比
    print(f"\n  v4a参考(无中性拆分, 6/3/3/3): 回测窗口不同, 参考之前+35.2%")


if __name__=="__main__":
    main()
