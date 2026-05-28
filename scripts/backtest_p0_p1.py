#!/usr/bin/env python3
"""P0 vs P1 vs P0+P1 四变体对比 — 一次跑完, 真实数字"""

import os, sys, io, math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from etf_engine import ETFS
from etf_signals import fetch, detect_trend, calc_rs, COMMISSION, SLIPPAGE, INITIAL, W_VOL, W_DIR, W_SHARE, DEFAULT_SHARE_RAW

def get_cfg(t):
    """2状态趋势配置 — 与生产 etf_engine.get_dynamic_params 一致 (2026-05-28简化)"""
    if t == "up":
        return {"cp_threshold": 50, "resonance_min": 2, "hold_days": 9, "allow_pyramiding": True}
    else:
        return {"cp_threshold": 50, "resonance_min": 3, "hold_days": 6, "allow_pyramiding": False}

# ---- ATR 计算 ----
def calc_atr_live(recs, day_i, period=14):
    if day_i < period+1: return None
    trs=[]
    for j in range(day_i-period+1, day_i+1):
        h,l=recs[j]["h"],recs[j]["l"]; pc=recs[j-1]["c"]
        tr=max(h-l,abs(h-pc),abs(l-pc)); trs.append(tr)
    return sum(trs)/len(trs) if trs else None

def get_atr_stop(code, recs, day_i, entry_price):
    """ATR动态止损: 高波动ETF用紧止损, 低波动ETF用宽止损"""
    atr = calc_atr_live(recs, day_i)
    if atr is None: return entry_price*0.97  # 回退3%
    atr_pct = atr/recs[day_i]["c"]*100
    if atr_pct > 2.0: mult=1.5   # 高波动: 1.5xATR ≈ 3-4%
    elif atr_pct > 1.0: mult=2.0 # 中波动: 2xATR ≈ 2-3%
    else: mult=3.0               # 低波动: 3xATR ≈ 2-3%
    return entry_price - atr*mult

# ---- 信号计算器 ----
class CPSystem:
    def __init__(self, data_dict):
        self.data_dict = data_dict
        self._share_cache = {}

    def compute(self, code, recs, ref, day_i, idx_chg):
        r=recs[day_i]; c,v=r["c"],r["v"]
        chg=(c-recs[day_i-1]["c"])/recs[day_i-1]["c"]*100
        vols=[recs[j]["v"] for j in range(max(0,day_i-20),day_i)]
        ma20=sum(vols)/len(vols) if vols else 1; vr=v/ma20 if ma20>0 else 1
        v_raw=min(1,max(0,(vr-0.7)/1.3)) if vr>=0.7 else 0
        rs,is_c=calc_rs(chg,idx_chg,vr); d_raw=rs/100

        share_raw = DEFAULT_SHARE_RAW
        delta = self._get_share_delta(code, ref[day_i]["date"])
        if delta is not None:
            dp = delta*0.7
            if dp>0.5: share_raw = min(1.0, 0.12+dp*0.06)
            elif dp<-1: share_raw = max(0.0, 0.12+dp*0.03)
            share_raw = max(0, min(1, share_raw))
        if idx_chg < 0:
            w_vol, w_dir = 0.45, 0.25
        else:
            w_vol, w_dir = W_VOL, W_DIR
        cp = (v_raw*w_vol + d_raw*w_dir + share_raw*W_SHARE)*100

        return cp, chg, vr, is_c, c

    def _get_share_delta(self, code, date):
        key=(code,date)
        if key in self._share_cache: return self._share_cache[key]
        recs=self.data_dict.get(code,[])
        di=None
        for i,r in enumerate(recs):
            if r["date"]==date: di=i; break
        if di is None or di<20: self._share_cache[key]=None; return None
        r=recs[di]; prev=recs[di-1]
        chg=(r["c"]-prev["c"])/prev["c"]*100 if prev["c"]>0 else 0
        vols=[recs[j]["v"] for j in range(di-20,di)]
        ma20=sum(vols)/len(vols) if vols else 1; vr=r["v"]/ma20 if ma20>0 else 1
        chg5=(r["c"]-recs[di-5]["c"])/recs[di-5]["c"]*100 if di>=5 else 0
        if chg>0.5 and vr>1.3 and chg5>0: delta=1.0+vr*1.0+min(chg5*0.3,2.0)
        elif chg<-1 and vr>1.5: delta=-1.0-vr*0.5-min(abs(chg5)*0.2,2.0)
        elif chg>0 and vr>1.0: delta=0.3+vr*0.5
        elif chg<-0.5: delta=-0.3-abs(chg5)*0.2
        else: delta=(chg*0.3+(vr-1)*0.5)*0.5
        delta=round(max(-5.0,min(8.0,delta)),2)
        self._share_cache[key]=delta
        return delta

# ---- 回测 ----
def run_backtest(data_dict, cp_sys, variant_name):
    """variant: 'baseline'|'p0'|'p1'|'p0p1'"""
    ref=data_dict.get("510300",[])
    if len(ref)<65: return [INITIAL],0,0,[]

    cash=INITIAL; holding={}; equity=[INITIAL]; trades=[]; signal_log=[]
    base_cooldown=0

    use_p1 = variant_name in ('p1','p0p1')

    for day_i in range(60,len(ref)-12):
        date=ref[day_i]["date"]
        if base_cooldown>0: base_cooldown-=1
        idx_c=ref[day_i]["c"]; idx_chg=(idx_c-ref[day_i-1]["c"])/ref[day_i-1]["c"]*100
        trend=detect_trend(ref,day_i); t=trend["trend"]; a=trend["above_ma"]; s=trend["strength"]
        cfg=get_cfg(t)

        if s>=70: min_pct=0.40
        elif s>=50 and t=="up": min_pct=0.25
        elif s>=50: min_pct=0.15
        else: min_pct=0

        total_eq=cash
        for code,pos in holding.items():
            recs=data_dict.get(code,data_dict.get("510300",[]))
            if day_i<len(recs) and recs[day_i]: total_eq+=pos["shares"]*recs[day_i]["c"]
            else: total_eq+=pos["shares"]*pos["entry_price"]
        cur_exp=(total_eq-cash)/total_eq if total_eq>0 else 0

        # 底仓
        if min_pct>0.15 and not [p for p in holding.values() if p.get("is_base")] and cur_exp<0.1 and a and s>55 and base_cooldown<=0:
            target=min(0.30,min_pct*0.6); ni=day_i+1
            if ni<len(ref)-5:
                op=ref[ni]["o"]
                if op>0:
                    alloc=cash*target; bp=op*(1+SLIPPAGE); sh=int(alloc/bp/100)*100
                    if sh>=100:
                        cost=sh*bp*(1+COMMISSION)
                        if cost<=cash:
                            cash-=cost
                            holding["510300_base"]={"shares":sh,"cost":cost,"entry_price":bp,"entry_date":ref[ni]["date"],"entry_i":ni,"highest":bp,"is_base":True}

        # 卖出
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
                recs=data_dict.get(code,[])
                cur_c=recs[day_i]["c"] if day_i<len(recs) and recs[day_i] else pos["entry_price"]
                should_exit=False; reason=""

                if day_i-pos["entry_i"]>=cfg["hold_days"]:
                    should_exit=True; reason="time"

                if use_p1:
                    # P1a: ATR动态止损
                    stop = get_atr_stop(code, recs, day_i, pos["entry_price"])
                    if cur_c <= stop:
                        should_exit=True; reason="atr_stop"

                    # P1b: 信号反转退出 (CP跌破阈值+趋势转负)
                    if not should_exit and day_i-pos["entry_i"]>=2:
                        cp_now,_,_,_,_ = cp_sys.compute(code, recs, ref, day_i, idx_chg)
                        if cp_now < cfg["cp_threshold"]*0.85:
                            chg_5d = ((cur_c - recs[day_i-5]["c"])/recs[day_i-5]["c"]*100) if day_i>=5 else 0
                            if chg_5d < -1.0:
                                should_exit=True; reason="signal_reverse"

                if should_exit:
                    sp=cur_c; pr=pos["shares"]*sp*(1-COMMISSION-SLIPPAGE); cash+=pr
                    trades.append({"profit_pct":round((pr/pos["cost"]-1)*100,2),"reason":reason})
                    to_sell.append(code)

        for code in to_sell: del holding[code]

        # 信号
        signals=[]
        for code,recs in data_dict.items():
            if code not in ETFS or day_i>=len(recs): continue
            cp,_,_,is_c,_=cp_sys.compute(code, recs, ref, day_i, idx_chg)
            if cp>=cfg["cp_threshold"]:
                signals.append({"code":code,"cp":cp,"is_counter":is_c})

        triggered=len(signals)>=cfg["resonance_min"]
        new_sigs=[s for s in signals if s["code"] not in holding]

        if triggered and new_sigs:
            ni=day_i+1
            if ni>=len(ref)-5: continue
            sc=sum(1 for p in holding.values() if not p.get("is_base"))
            ms=6 if cfg["allow_pyramiding"] else 4
            if sc>=ms: continue
            bl=sorted(new_sigs,key=lambda x:x["cp"],reverse=True)[:min(4,ms-sc)]
            tb=cash*0.8; alloc=tb/max(len(bl),1)
            for sig in bl:
                recs=data_dict.get(sig["code"],[])
                if ni>=len(recs): continue
                op=recs[ni]["o"]
                if op<=0: continue
                bp=op*(1+SLIPPAGE); sh=int(alloc/bp/100)*100
                if sh<100: continue
                cost=sh*bp*(1+COMMISSION)
                if cost>cash: continue
                cash-=cost; holding[sig["code"]]={"shares":sh,"cost":cost,"entry_price":bp,"entry_date":ref[ni]["date"],"entry_i":ni,"highest":bp,"cp":sig["cp"]}

        total=cash
        for code,pos in holding.items():
            recs=data_dict.get(code,data_dict.get("510300",[]))
            if day_i<len(recs) and recs[day_i]: total+=pos["shares"]*recs[day_i]["c"]
            else: total+=pos["shares"]*pos["entry_price"]
        equity.append(total)

    li=len(ref)-13
    for code,pos in holding.items():
        recs=data_dict.get(code,data_dict.get("510300",[]))
        sp=recs[li]["c"] if li<len(recs) and recs[li] else pos["entry_price"]
        pr=pos["shares"]*sp*(1-COMMISSION-SLIPPAGE); cash+=pr
    equity.append(cash)
    wr=sum(1 for t in trades if t.get("profit_pct",0)>0)/max(len(trades),1)*100
    return equity,len(trades),round(wr,1),trades

def buy_hold(data_dict):
    recs=data_dict.get("510300",[])
    if len(recs)<65: return [INITIAL]
    si,ei=60,len(recs)-13; sh=int(INITIAL/recs[si]["c"]/100)*100
    return [sh*recs[i]["c"] for i in range(si,ei+1)]

def calc_metrics(equity, n_trades, wr, name):
    if len(equity)<2: return {"name":name,"ret":0,"dd":0,"sh":0,"ar":0,"n":0,"wr":0}
    tr=(equity[-1]/equity[0]-1)*100
    ar=((equity[-1]/equity[0])**(252/max(len(equity),1))-1)*100
    peak=equity[0]; md=0
    for v in equity:
        dd=(v-peak)/peak*100
        if v>peak: peak=v; dd=0
        if dd<md: md=dd
    dr=[(equity[i]/equity[i-1]-1) for i in range(1,len(equity))]
    sh=(sum(dr)/len(dr)/((sum((r-sum(dr)/len(dr))**2 for r in dr)/len(dr))**0.5)*(252**0.5)) if dr else 0
    return {"name":name,"ret":round(tr,2),"dd":round(md,2),"sh":round(sh,2),"ar":round(ar,2),"n":n_trades,"wr":round(wr,1)}

def main():
    print("="*100)
    print("P0 vs P1 vs P0+P1  四变体完整对比")
    print("="*100)

    print("\n⏳ 拉取15只ETF K线...")
    data_dict={}
    for code in ETFS:
        data_dict[code]=fetch(code,800)
    ref=data_dict["510300"]
    rd=[r["date"] for r in ref]
    print(f"  数据: {rd[0]} ~ {rd[-1]}")

    periods=[("3年","2023-05","2026-05"),("2年","2024-05","2026-05"),("1年","2025-05","2026-05")]

    variants=[("p0","P0:统一权重"),("p1","P1:ATR+信号退出"),("p0p1","P0+P1:全修")]

    all_res={}

    for pname,spfx,epfx in periods:
        mask=[i for i,d in enumerate(rd) if d>=spfx and d<=epfx]
        si,ei=max(60,mask[0]),min(len(ref)-13,mask[-1])
        precs={c:[d for d in data_dict[c][si:ei+1]] for c in data_dict if si<len(data_dict[c]) and ei<len(data_dict[c])}
        if "510300" not in precs or len(precs["510300"])<65: continue

        print(f"\n{'─'*100}")
        print(f"📅 {pname} ({precs['510300'][0]['date']} ~ {precs['510300'][-1]['date']})")
        print(f"{'─'*100}")
        print(f"  {'变体':<28} {'收益':>8} {'年化':>8} {'回撤':>7} {'夏普':>6} {'胜率':>6} {'交易':>5}")
        print(f"  {'─'*28} {'─'*8} {'─'*8} {'─'*7} {'─'*6} {'─'*6} {'─'*5}")

        period_res={}
        for vmode,vlabel in variants:
            cp_sys=CPSystem(data_dict)
            eq,nt,wr,trades=run_backtest(precs, cp_sys, vmode)
            m=calc_metrics(eq,nt,wr,vlabel)
            period_res[vlabel]=m
            print(f"  {vlabel:<28} {m['ret']:>+7.1f}% {m['ar']:>+7.1f}% {m['dd']:>+6.1f}% {m['sh']:>5.2f} {m['wr']:>5.1f}% {m['n']:>5}")

        ebh=buy_hold(precs); mbh=calc_metrics(ebh,0,0,"买持")
        period_res["买持"]=mbh
        print(f"  {'买持':<28} {mbh['ret']:>+7.1f}% {mbh['ar']:>+7.1f}% {mbh['dd']:>+6.1f}% {mbh['sh']:>5.2f}")
        all_res[pname]=period_res

    # ==== 终局对比 ====
    print(f"\n{'='*100}")
    print("终局对比: 每个变体相对旧回测的提升")
    print(f"{'='*100}")

    for pname in ["3年","2年","1年"]:
        if pname not in all_res: continue
        res=all_res[pname]
        print(f"\n  [{pname}]")
        for vlabel in ["P0:统一权重","P1:ATR+信号退出","P0+P1:全修"]:
            if vlabel not in res: continue
            m=res[vlabel]
            print(f"    {vlabel:<20} 收益{m['ret']:+.1f}%  回撤{m['dd']:+.1f}%  夏普{m['sh']:.2f}  交易{m['n']}")

    # 结论
    print(f"\n{'='*100}")
    print("结论")
    print(f"{'='*100}")
    best_variant = None
    best_avg = -999
    for vlabel in ["P0:统一权重","P1:ATR+信号退出","P0+P1:全修"]:
        scores=[]
        for pname in ["3年","2年","1年"]:
            if pname in all_res and vlabel in all_res[pname]:
                scores.append(all_res[pname][vlabel]["sh"])
        if len(scores)==3:
            avg=sum(scores)/3
            print(f"  {vlabel:<28} 平均夏普: {avg:.2f}")
            if avg>best_avg: best_avg=avg; best_variant=vlabel
    print(f"\n  推荐部署: {best_variant}")

if __name__=="__main__":
    main()
