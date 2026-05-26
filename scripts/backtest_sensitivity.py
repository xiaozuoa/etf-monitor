#!/usr/bin/env python3
"""份额因子敏感性回测: share_raw=0.05→0.35 对策略P&L的量化影响"""

import os, sys, io, json, urllib.request, ssl, math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from etf_engine import ETFS, calc_relative_strength

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False; SSL_CTX.verify_mode = ssl.CERT_NONE
COMMISSION=0.00025; SLIPPAGE=0.0005; INITIAL=100000
WEIGHTS = {"vol":0.50, "dir":0.20, "share":0.30}

def fetch(code, limit=800):
    pfx="sh" if code.startswith(("51","56","0")) else "sz"
    if code.startswith(("sh","sz")): pfx2,nc=code[:2],code[2:]
    else: pfx2,nc=pfx,code
    u=f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={pfx2}{nc},day,,,{limit},qfq"
    req=urllib.request.Request(u,headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=15,context=SSL_CTX) as r:
        d=json.loads(r.read().decode("utf-8"))
    k=d.get("data",{}).get(f"{pfx2}{nc}",{}).get("qfqday",[]) or d.get("data",{}).get(f"{pfx2}{nc}",{}).get("day",[])
    return [{"date":r[0],"o":float(r[1]),"c":float(r[2]),"h":float(r[3]),"l":float(r[4]),"v":float(r[5])}
            for r in k if len(r)>=6 and r[0]]

def detect_trend(ref,day_i):
    if day_i<50: return {"trend":"neutral","slope":0,"strength":50,"above_ma":True}
    closes=[d["c"] for d in ref[day_i-49:day_i+1]]
    ma_now=sum(closes)/len(closes); ma_10d=sum(closes[:10])/10
    slope=(ma_now-ma_10d)/ma_10d*100 if ma_10d>0 else 0
    above=ref[day_i]["c"]>ma_now
    if slope>1.0 and above: t="up"
    elif slope<-1.0 and not above: t="down"
    else: t="neutral"
    s=min(100,50+slope*15) if t!="neutral" else 50
    return {"trend":t,"slope":round(slope,2),"strength":round(s,1),"above_ma":above}

def get_cfg(t,a):
    if t=="up": return {"cp_threshold":45,"resonance_min":2,"hold_days":10,"allow_pyramiding":True}
    elif t=="down": return {"cp_threshold":50,"resonance_min":4,"hold_days":4,"allow_pyramiding":False}
    else:
        if a: return {"cp_threshold":50,"resonance_min":2,"hold_days":7,"allow_pyramiding":False}
        else: return {"cp_threshold":50,"resonance_min":5,"hold_days":4,"allow_pyramiding":False}

def run_backtest(data_dict, share_raw_value):
    """回测, share_raw=固定值 (模拟不同的份额因子强度)"""
    ref=data_dict.get("510300",[])
    if len(ref)<55: return [INITIAL],0
    cash=INITIAL; holding={}; equity=[INITIAL]; trades=[]
    base_cooldown=0

    for day_i in range(50,len(ref)-12):
        date=ref[day_i]["date"]
        if base_cooldown>0: base_cooldown-=1
        idx_c=ref[day_i]["c"]; idx_chg=(idx_c-ref[day_i-1]["c"])/ref[day_i-1]["c"]*100
        trend=detect_trend(ref,day_i); t=trend["trend"]; a=trend["above_ma"]; s=trend["strength"]
        cfg=get_cfg(t,a)

        if s>=70: min_pct=0.40
        elif s>=50 and t=="up": min_pct=0.25
        elif s>=50: min_pct=0.15
        else: min_pct=0

        total_eq=cash
        for _,pos in holding.items():
            total_eq+=pos["shares"]*ref[day_i]["c"] if day_i<len(ref) else pos["shares"]*pos["entry_price"]
        cur_exp=(total_eq-cash)/total_eq if total_eq>0 else 0

        if min_pct>0.15 and len([p for p in holding.values() if p.get("is_base")])==0 and cur_exp<0.1 and a and s>55 and base_cooldown<=0:
            target=min(0.30,min_pct*0.6); next_i=day_i+1
            if next_i<len(ref)-5:
                op=ref[next_i]["o"]
                if op>0:
                    alloc=cash*target; bp=op*(1+SLIPPAGE); sh=int(alloc/bp/100)*100
                    if sh>=100:
                        cost=sh*bp*(1+COMMISSION)
                        if cost<=cash: cash-=cost; holding["base"]={"shares":sh,"cost":cost,"entry_price":bp,"entry_date":ref[next_i]["date"],"entry_i":next_i,"highest":bp,"is_base":True}

        to_sell=[]
        for code,pos in holding.items():
            if pos.get("is_base"):
                exit_base=False; cur_c=ref[day_i]["c"] if day_i<len(ref) else pos["entry_price"]
                if t=="down" and s<40: exit_base=True
                if not a and trend["slope"]<-0.5: exit_base=True
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

        signals=[]
        for code,recs in data_dict.items():
            if code not in ETFS or day_i>=len(recs): continue
            r=recs[day_i]; c,v=r["c"],r["v"]
            chg=(c-recs[day_i-1]["c"])/recs[day_i-1]["c"]*100
            vols=[recs[j]["v"] for j in range(max(0,day_i-19),day_i+1)]
            ma20=sum(vols)/len(vols); vr=v/ma20 if ma20>0 else 1
            v_raw=min(1,max(0,(vr-0.7)/1.3)) if vr>=0.7 else 0
            rs,is_c=calc_relative_strength(chg,idx_chg,vr); d_raw=rs/100

            cp=(v_raw*WEIGHTS["vol"]+d_raw*WEIGHTS["dir"]+share_raw_value*WEIGHTS["share"])*100
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
            for sig in bl:
                recs=data_dict.get(sig["code"],[])
                if next_i>=len(recs): continue
                op=recs[next_i]["o"]
                if op<=0: continue
                bp=op*(1+SLIPPAGE); sh=int(alloc/bp/100)*100
                if sh<100: continue
                cost=sh*bp*(1+COMMISSION)
                if cost>cash: continue
                cash-=cost; holding[sig["code"]]={"shares":sh,"cost":cost,"entry_price":bp,"entry_date":ref[next_i]["date"],"entry_i":next_i,"highest":bp}

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
    return equity,len(trades)

def buy_hold(data_dict):
    recs=data_dict.get("510300",[])
    if len(recs)<55: return [INITIAL]
    si,ei=50,len(recs)-13; sh=int(INITIAL/recs[si]["c"]/100)*100
    return [sh*recs[i]["c"] for i in range(si,ei+1)]

def metrics(equity, trades, name):
    if len(equity)<2: return {"name":name,"total_return":0,"max_drawdown":0,"sharpe":0,"annual":0,"trades":0}
    tr=(equity[-1]/equity[0]-1)*100
    ar=((equity[-1]/equity[0])**(252/len(equity))-1)*100
    peak=equity[0]; md=0
    for v in equity:
        dd=(v-peak)/peak*100
        if v>peak: peak=v; dd=0
        if dd<md: md=dd
    dr=[(equity[i]/equity[i-1]-1) for i in range(1,len(equity))]
    sh=(sum(dr)/len(dr)/((sum((r-sum(dr)/len(dr))**2 for r in dr)/len(dr))**0.5)*(252**0.5)) if dr else 0
    return {"name":name,"total_return":round(tr,2),"max_drawdown":round(md,2),
            "sharpe":round(sh,2),"annual":round(ar,2),"trades":trades}

def main():
    print("="*80)
    print("份额因子敏感性回测")
    print("="*80)

    print("\n⏳ 拉取15只ETF K线...")
    data_dict={}
    for code in ETFS:
        data_dict[code]=fetch(code,800)
    ref=data_dict["510300"]
    ref_dates=[r["date"] for r in ref]
    print(f"  数据: {ref_dates[0]} ~ {ref_dates[-1]} ({len(ref)}条)")

    # 分三个周期
    periods=[("3年","2023-05","2026-05"),("2年","2024-05","2026-05"),("1年","2025-05","2026-05")]

    # share_raw 扫描范围
    share_values = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30, 0.35]
    labels = {0.05:"强赎回", 0.08:"中度赎回", 0.10:"轻度赎回", 0.12:"中性(改进前)",
              0.15:"轻度申购", 0.20:"中度申购", 0.25:"强申购", 0.30:"大额申购", 0.35:"极端申购"}

    all_period_results = {}

    for pname, spfx, epfx in periods:
        mask=[i for i,d in enumerate(ref_dates) if d>=spfx and d<=epfx]
        si,ei=max(50,mask[0]),min(len(ref)-13,mask[-1])
        if si>=ei: continue

        precs={}
        for c in data_dict:
            dlist=data_dict[c]
            if si<len(dlist) and ei<len(dlist):
                precs[c]=dlist[si:ei+1]
        if "510300" not in precs or len(precs["510300"])<55: continue

        print(f"\n{'─'*80}")
        print(f"📅 {pname} ({precs['510300'][0]['date']} ~ {precs['510300'][-1]['date']})")
        print(f"{'─'*80}")

        period_results=[]

        for sv in share_values:
            equity,trades=run_backtest(precs, sv)
            m=metrics(equity,trades,f"share={sv:.2f}")
            period_results.append(m)
            label=labels.get(sv,"")
            print(f"  share={sv:.2f} ({label:<12}) 收益{m['total_return']:>+7.1f}%  回撤{m['max_drawdown']:>+6.1f}%  "
                  f"夏普{m['sharpe']:>5.2f}  年化{m['annual']:>+6.1f}%  交易{m['trades']:>4}")

        # 买持
        ebh=buy_hold(precs); mbh=metrics(ebh,0,"买持")
        period_results.append(mbh)
        print(f"  {'买持基准':<22} 收益{mbh['total_return']:>+7.1f}%  回撤{mbh['max_drawdown']:>+6.1f}%  "
              f"夏普{mbh['sharpe']:>5.2f}  年化{mbh['annual']:>+6.1f}%")

        all_period_results[pname]=period_results

    # ==== 汇总 ====
    print(f"\n{'='*80}")
    print("📊 跨周期汇总")
    print(f"{'='*80}")

    for pname in ["3年","2年","1年"]:
        if pname not in all_period_results: continue
        results=[r for r in all_period_results[pname] if r["name"]!="买持"]
        if not results: continue

        best=sorted(results,key=lambda x:x["total_return"],reverse=True)[0]
        worst=sorted(results,key=lambda x:x["total_return"])[0]
        baseline=[r for r in results if r["name"]=="share=0.12"][0]

        print(f"\n  [{pname}]")
        print(f"    share=0.12 (改进前基准):  {baseline['total_return']:+.1f}%  SH={baseline['sharpe']:.2f}")
        print(f"    最优 share:  {best['name']} → {best['total_return']:+.1f}%  (vs基准 {best['total_return']-baseline['total_return']:+.1f}%)")
        print(f"    最差 share:  {worst['name']} → {worst['total_return']:+.1f}%  (vs基准 {worst['total_return']-baseline['total_return']:+.1f}%)")
        print(f"    极差: {best['total_return']-worst['total_return']:.1f}% (share从{worst['name'].split('=')[-1]}→{best['name'].split('=')[-1]})")

    # 结论
    print(f"\n{'='*80}")
    print("结论")
    print(f"{'='*80}")
    print("  改进前: share_raw=0.12, 所有ETF统一, 份额30%权重没有区分度")
    print("  改进后: 申购ETF share>0.12, 赎回ETF share<0.12 → CP有升有降")
    print("  上表展示的是 '如果份额因子的有效值在X附近, 策略收益会变多少'")
    print("  share从0.05→0.35的范围覆盖了赎回→大额申购的全部场景")
    print("  差值越大 → 说明30%权重的影响力越大")
    print("  ")
    print("  注意: 这是固定share值的敏感性分析, 不是用真实份额变化率跑的回测")
    print("  真实份额数据需要akshare → 在GitHub Actions环境可获取 → 建议添加CI对比job")

if __name__=="__main__":
    main()
