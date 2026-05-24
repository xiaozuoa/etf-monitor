#!/usr/bin/env python3
"""全模型×全周期对比 — 15只ETF池"""

import os, sys, io, json, urllib.request, ssl
from collections import defaultdict

if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from etf_engine import ETFS, calc_relative_strength

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

def calc_rs(etf_chg, idx_chg, vol_ratio):
    excess=etf_chg-idx_chg; score,is_c=0,False
    if idx_chg<-0.5 and etf_chg>idx_chg+0.3: score+=40;is_c=True
    if idx_chg<-1.5 and is_c: score+=min(20,abs(idx_chg)*3)
    if idx_chg<-0.5 and vol_ratio>1.3 and etf_chg>idx_chg+0.5: score+=25
    if excess>0.3: score+=min(20,excess*6)
    if idx_chg>1.5 and 0<excess<0.3: score-=15
    if idx_chg>2.0 and excess<0.5: score-=10
    if etf_chg>1.5 and vol_ratio<0.8: score-=20
    return max(0,min(100,score)),is_c

def compute_cp(records, day_i, idx_chg):
    r=records[day_i]; c,v=r["c"],r["v"]
    chg=(c-records[day_i-1]["c"])/records[day_i-1]["c"]*100
    vols=[records[j]["v"] for j in range(max(0,day_i-19),day_i+1)]
    ma20=sum(vols)/len(vols); vr=v/ma20 if ma20>0 else 1
    v_raw=min(1,max(0,(vr-0.7)/1.3)) if vr>=0.7 else 0
    rs,is_c=calc_rs(chg,idx_chg,vr); d_raw=rs/100
    return (v_raw*0.55+d_raw*0.40+0.12*0.05)*100, chg, vr, is_c, c

# ============= 模型定义 =============

def get_config_v3():
    """v3: 固定参数, 无趋势"""
    return {"fixed": True, "label": "v3固定",
            "config": {"default": {"cp_threshold":50,"resonance_min":3,"hold_days":3,"allow_pyramiding":False}}}

def get_config_v4a():
    """v4a: 趋势自适应, 无中性拆分, 无底仓"""
    return {"fixed": False, "use_base": False, "label": "v4a趋势",
            "config_fn": lambda t, a: (
                {"cp_threshold":45,"resonance_min":2,"hold_days":6,"allow_pyramiding":True}
                if t=="up" else
                {"cp_threshold":50,"resonance_min":3,"hold_days":3,"allow_pyramiding":False}
                if t=="down" else
                {"cp_threshold":50,"resonance_min":3,"hold_days":3,"allow_pyramiding":False}
            )}

def get_config_v4a_opt():
    """v4a+持有期优化: 6/4/3 → 10/7/4/3"""
    return {"fixed": False, "use_base": False, "label": "v4a+持优",
            "config_fn": lambda t, a: (
                {"cp_threshold":45,"resonance_min":2,"hold_days":10,"allow_pyramiding":True}
                if t=="up" else
                {"cp_threshold":50,"resonance_min":3,"hold_days":3,"allow_pyramiding":False}
                if t=="down" else
                {"cp_threshold":50,"resonance_min":3,"hold_days":3,"allow_pyramiding":False}
            )}

def get_config_v5():
    """v5: 中性拆分+底仓 (9只版参数)"""
    return {"fixed": False, "use_base": True, "label": "v5中性+底仓",
            "config_fn": lambda t, a: (
                {"cp_threshold":45,"resonance_min":2,"hold_days":6,"allow_pyramiding":True}
                if t=="up" else
                {"cp_threshold":50,"resonance_min":3,"hold_days":3,"allow_pyramiding":False}
                if t=="down" else (
                    {"cp_threshold":50,"resonance_min":2,"hold_days":4,"allow_pyramiding":False}
                    if a else
                    {"cp_threshold":50,"resonance_min":3,"hold_days":3,"allow_pyramiding":False}
                )
            )}

def get_config_v5_opt():
    """v5+持有期优化(10/7/4/3, 9只版共振)"""
    return {"fixed": False, "use_base": True, "label": "v5+持优(9只)",
            "config_fn": lambda t, a: (
                {"cp_threshold":45,"resonance_min":2,"hold_days":10,"allow_pyramiding":True}
                if t=="up" else
                {"cp_threshold":50,"resonance_min":3,"hold_days":3,"allow_pyramiding":False}
                if t=="down" else (
                    {"cp_threshold":50,"resonance_min":2,"hold_days":7,"allow_pyramiding":False}
                    if a else
                    {"cp_threshold":50,"resonance_min":3,"hold_days":4,"allow_pyramiding":False}
                )
            )}

def get_config_current():
    """当前最优: 15只池4212组合网格搜索"""
    return {"fixed": False, "use_base": True, "label": "当前(15只优)",
            "config_fn": lambda t, a: (
                {"cp_threshold":45,"resonance_min":2,"hold_days":10,"allow_pyramiding":True}
                if t=="up" else
                {"cp_threshold":50,"resonance_min":4,"hold_days":4,"allow_pyramiding":False}
                if t=="down" else (
                    {"cp_threshold":50,"resonance_min":2,"hold_days":7,"allow_pyramiding":False}
                    if a else
                    {"cp_threshold":50,"resonance_min":5,"hold_days":4,"allow_pyramiding":False}
                )
            )}

# ============= 统一回测 =============

def backtest(data_dict, model_def):
    ref = data_dict.get("510300",[])
    if len(ref)<55: return [],[INITIAL]

    cash=INITIAL; holding={}; equity=[INITIAL]; trades=[]
    base_cooldown=0; use_base=model_def.get("use_base",False)
    fixed=model_def.get("fixed",False)

    for day_i in range(50, len(ref)-12):
        date=ref[day_i]["date"]
        if base_cooldown>0: base_cooldown-=1
        idx_c=ref[day_i]["c"]; idx_chg=(idx_c-ref[day_i-1]["c"])/ref[day_i-1]["c"]*100
        trend=detect_trend(ref,day_i)
        t=trend["trend"]; a=trend["above_ma"]; s=trend["strength"]

        if fixed: cfg=model_def["config"]["default"]
        else: cfg=model_def["config_fn"](t,a)

        # 底仓
        if use_base:
            if s>=70: min_pct=0.40
            elif s>=50 and t=="up": min_pct=0.25
            elif s>=50: min_pct=0.15
            else: min_pct=0
        else: min_pct=0

        total_eq=cash
        for _,pos in holding.items():
            r3=data_dict.get("510300",[])
            if day_i<len(r3) and r3[day_i]: total_eq+=pos["shares"]*r3[day_i]["c"]
            else: total_eq+=pos["shares"]*pos["entry_price"]
        cur_exp=(total_eq-cash)/total_eq if total_eq>0 else 0

        if use_base and min_pct>0.15 and len(holding)==0 and cur_exp<0.1 and a and s>55 and not base_cooldown:
            target=min(0.30, min_pct*0.6); next_i=day_i+1
            if next_i<len(ref)-5:
                r3=data_dict.get("510300",[])
                if next_i<len(r3):
                    op=r3[next_i]["o"]
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

        # 信号
        signals=[]
        for code,recs in data_dict.items():
            if code not in ETFS or day_i>=len(recs): continue
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

def buy_hold(data_dict):
    recs=data_dict.get("510300",[])
    if len(recs)<55: return [INITIAL]
    si,ei=50,len(recs)-13; sh=int(INITIAL/recs[si]["c"]/100)*100
    return [sh*recs[i]["c"] for i in range(si,ei+1)]

def metrics(equity, trades, name):
    if len(equity)<2: return {"name":name,"total_return":0,"max_drawdown":0,"sharpe":0,"annual":0,"trades":0}
    tr=(equity[-1]/equity[0]-1)*100
    ar=((equity[-1]/equity[0])**(252/max(len(equity),1))-1)*100
    peak=equity[0]; md=0
    for v in equity:
        dd=(v-peak)/peak*100
        if v>peak: peak=v; dd=0
        if dd<md: md=dd
    dr=[(equity[i]/equity[i-1]-1) for i in range(1,len(equity))]
    sh=(sum(dr)/len(dr)/((sum((r-sum(dr)/len(dr))**2 for r in dr)/len(dr))**0.5)*(252**0.5)) if dr else 0
    return {"name":name,"total_return":round(tr,2),"max_drawdown":round(md,2),
            "sharpe":round(sh,2),"annual":round(ar,2),"trades":len(trades)}


def main():
    print("="*90)
    print("全模型×全周期 横向对比 (15只ETF)")
    print("="*90)

    print("\nLoading 15 ETFs...")
    data_dict={}
    for code in ETFS:
        data_dict[code]=fetch(code,800)
    ref=data_dict["510300"]; ref_dates=[r["date"] for r in ref]

    periods=[("1年","2025-05","2026-05"),("2年","2024-05","2026-05"),("3年","2023-05","2026-05")]
    models=[get_config_v3(), get_config_v4a(), get_config_v4a_opt(),
            get_config_v5(), get_config_v5_opt(), get_config_current()]
    model_names=[m["label"] for m in models]

    all_results={}
    for pname,spfx,epfx in periods:
        mask=[i for i,d in enumerate(ref_dates) if d>=spfx and d<=epfx]
        si,ei=max(50,mask[0]),min(len(ref)-13,mask[-1])
        precs={c:[r for r in data_dict[c][si:ei+1]] for c in data_dict if si<len(data_dict[c]) and ei<len(data_dict[c])}

        print(f"\n--- {pname} ({precs['510300'][0]['date']}~{precs['510300'][-1]['date']}) ---")

        period_results={}
        for model in models:
            _,eq=backtest(precs, model)
            m=metrics(eq,[],model["label"])
            period_results[model["label"]]=m
            print(f"  {m['name']:<16} Ret:{m['total_return']:>+7.1f}% DD:{m['max_drawdown']:>+5.1f}% SH:{m['sharpe']:.2f} Tr:{m['trades']:>4}")

        ebh=buy_hold(precs); mbh=metrics(ebh,[],"买持")
        period_results["买持"]=mbh
        print(f"  {'买持':<16} Ret:{mbh['total_return']:>+7.1f}% DD:{mbh['max_drawdown']:>+5.1f}% SH:{mbh['sharpe']:.2f}")

        all_results[pname]=period_results

    # 汇总排名
    print(f"\n{'='*90}")
    print(f"跨周期汇总 — 每个周期的第一名")
    print(f"{'='*90}")
    for pname in ["1年","2年","3年"]:
        if pname not in all_results: continue
        results=all_results[pname]
        best=sorted([(k,v) for k,v in results.items() if k!="买持"], key=lambda x: x[1]["total_return"], reverse=True)
        print(f"\n  {pname}:")
        for rank,(name,m) in enumerate(best,1):
            flag=" <-- 最优" if rank==1 else ""
            print(f"    {rank}. {name:<16} +{m['total_return']:.1f}% DD{m['max_drawdown']:.1f}% SH{m['sharpe']:.2f}{flag}")

    # 最终结论
    print(f"\n{'='*90}")
    print(f"最终结论")
    print(f"{'='*90}")

    # 统计每个模型在各周期的排名
    model_scores={}
    for pname in ["1年","2年","3年"]:
        if pname not in all_results: continue
        results=all_results[pname]
        sorted_models=sorted([(k,v) for k,v in results.items() if k!="买持"], key=lambda x: x[1]["total_return"], reverse=True)
        for rank,(name,_) in enumerate(sorted_models,1):
            model_scores[name]=model_scores.get(name,0)+(len(sorted_models)-rank+1)

    best_overall=sorted(model_scores.items(), key=lambda x: x[1], reverse=True)
    print("综合评分(跨周期):")
    for name,score in best_overall:
        print(f"  {name:<16} {score}分")

    print(f"\n部署: {best_overall[0][0]}")


if __name__=="__main__":
    main()
