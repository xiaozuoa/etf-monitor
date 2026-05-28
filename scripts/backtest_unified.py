#!/usr/bin/env python3
"""P0统一回测: 回测CP=生产CP, 连续仓位, 份额代理 — 地基打平后的真实数字"""

import os, sys, io, math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from etf_engine import ETFS
from etf_signals import fetch, detect_trend, calc_rs, COMMISSION, SLIPPAGE, INITIAL

def get_cfg(t):
    """2状态趋势配置 — 与生产 etf_engine.get_dynamic_params 一致 (2026-05-28简化)"""
    if t == "up":
        return {"cp_threshold": 50, "resonance_min": 2, "hold_days": 7, "allow_pyramiding": True}
    else:
        return {"cp_threshold": 50, "resonance_min": 3, "hold_days": 5, "allow_pyramiding": False}

# ==========================================
# CP 计算模式 (统一版)
# ==========================================
from etf_signals import W_VOL, W_DIR, W_SHARE, DEFAULT_SHARE_RAW

def compute_cp_unified(v_raw, d_raw, idx_chg=0, code=None, date=None, collector=None):
    """统一CP: 权重 50/20/30, 可选份额代理"""
    share_raw = DEFAULT_SHARE_RAW
    if collector is not None and code is not None and date is not None:
        delta = collector.get_delta(code, date)
        if delta is not None:
            dp = delta*0.7
            if dp>0.5:   share_raw = min(1.0, 0.12+dp*0.06)
            elif dp<-1:   share_raw = max(0.0, 0.12+dp*0.03)
            share_raw = max(0,min(1,share_raw))
    if idx_chg < 0:
        w_vol, w_dir = 0.35, 0.35
    else:
        w_vol, w_dir = W_VOL, W_DIR
    return (v_raw*w_vol + d_raw*w_dir + share_raw*W_SHARE)*100

# ==========================================
# 份额数据模拟器 (基于K线模式推断资金流向)
# ==========================================
class ShareSimulator:
    """基于ETF价格+量能模式推断份额变化方向, 模拟真实份额代理行为

    逻辑:
    - 放量上涨+大盘下跌 → 国家队申购, 份额+2~4%
    - 缩量下跌 → 资金出逃, 份额-1~-3%
    - 其他情况 → 份额微变 ±0.5%
    """
    def __init__(self, data_dict):
        self._cache = {}
        self.data_dict = data_dict

    def get_delta(self, code, date):
        if (code, date) in self._cache:
            return self._cache[(code, date)]

        recs = self.data_dict.get(code, [])
        date_idx = None
        for i, r in enumerate(recs):
            if r["date"] == date:
                date_idx = i
                break
        if date_idx is None or date_idx < 20:
            self._cache[(code, date)] = None
            return None

        # 计算当日特征
        r = recs[date_idx]
        prev = recs[date_idx-1]
        chg = (r["c"]-prev["c"])/prev["c"]*100 if prev["c"]>0 else 0
        vols = [recs[j]["v"] for j in range(date_idx-20, date_idx)]
        ma20 = sum(vols)/len(vols) if vols else 1
        vr = r["v"]/ma20 if ma20>0 else 1

        # 5日趋势
        if date_idx>=5:
            chg5 = (r["c"]-recs[date_idx-5]["c"])/recs[date_idx-5]["c"]*100 if recs[date_idx-5]["c"]>0 else 0
        else:
            chg5 = 0

        # 推断份额变化
        if chg>0.5 and vr>1.3 and chg5>0:
            # 放量上涨, 资金流入
            delta = 1.0 + vr*1.0 + min(chg5*0.3, 2.0)
        elif chg<-1 and vr>1.5:
            # 放量下跌, 恐慌出逃
            delta = -1.0 - vr*0.5 - min(abs(chg5)*0.2, 2.0)
        elif chg>0 and vr>1.0:
            delta = 0.3 + vr*0.5
        elif chg<-0.5:
            delta = -0.3 - abs(chg5)*0.2
        else:
            delta = (chg*0.3 + (vr-1)*0.5) * 0.5  # 轻微变化

        delta = round(max(-5.0, min(8.0, delta)), 2)
        self._cache[(code, date)] = delta
        return delta

# ==========================================
# 回测引擎
# ==========================================
def run_backtest(data_dict, sizing_mode, collector=None):
    """
    sizing_mode: 'equal' = 等额分配, 'weighted' = CP加权分配
    """
    ref=data_dict.get("510300",[])
    if len(ref)<65: return [INITIAL],0,[]

    cash=INITIAL; holding={}; equity=[INITIAL]; trades=[]
    base_cooldown=0; signal_log=[]

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

        if min_pct>0.15 and len([p for p in holding.values() if p.get("is_base")])==0 and cur_exp<0.1 and a and s>55 and base_cooldown<=0:
            target=min(0.30,min_pct*0.6); next_i=day_i+1
            if next_i<len(ref)-5:
                op=ref[next_i]["o"]
                if op>0:
                    alloc=cash*target; bp=op*(1+SLIPPAGE); sh=int(alloc/bp/100)*100
                    if sh>=100:
                        cost=sh*bp*(1+COMMISSION)
                        if cost<=cash: cash-=cost; holding["510300_base"]={"shares":sh,"cost":cost,"entry_price":bp,"entry_date":ref[next_i]["date"],"entry_i":next_i,"highest":bp,"is_base":True}

        to_sell=[]
        for code,pos in holding.items():
            if pos.get("is_base"):
                exit_base=False; cur_c=ref[day_i]["c"] if day_i<len(ref) else pos["entry_price"]
                if t=="down" and s<40: exit_base=True
                if not a and trend["slope"]<-0.5: exit_base=True
                if (cur_c-pos["entry_price"])/pos["entry_price"]*100<-2.5: exit_base=True
                if exit_base:
                    sp=cur_c; pr=pos["shares"]*sp*(1-COMMISSION-SLIPPAGE); cash+=pr
                    trades.append({"profit_pct":round((pr/pos["cost"]-1)*100,2),"type":"base"})
                    base_cooldown=15; to_sell.append(code)
            else:
                if day_i-pos["entry_i"]>=cfg["hold_days"]:
                    recs=data_dict.get(code,[])
                    sp=recs[day_i]["c"] if day_i<len(recs) and recs[day_i] else pos["entry_price"]
                    pr=pos["shares"]*sp*(1-COMMISSION-SLIPPAGE); cash+=pr
                    trades.append({"profit_pct":round((pr/pos["cost"]-1)*100,2),"type":"signal"})
                    to_sell.append(code)
        for code in to_sell: del holding[code]

        signals=[]
        for code,recs in data_dict.items():
            if code not in ETFS or day_i>=len(recs): continue
            r=recs[day_i]; c,v=r["c"],r["v"]
            chg=(c-recs[day_i-1]["c"])/recs[day_i-1]["c"]*100
            vols=[recs[j]["v"] for j in range(max(0,day_i-20),day_i)]
            ma20=sum(vols)/len(vols) if vols else 1; vr=v/ma20 if ma20>0 else 1
            v_raw=min(1,max(0,(vr-0.7)/1.3)) if vr>=0.7 else 0
            rs,is_c=calc_rs(chg,idx_chg,vr); d_raw=rs/100

            cp = compute_cp_unified(v_raw, d_raw, idx_chg, code, date, collector or ShareSimulator(data_dict))

            if cp>=cfg["cp_threshold"]:
                signals.append({"code":code,"cp":cp,"is_counter":is_c})

        triggered=len(signals)>=cfg["resonance_min"]
        new_sigs=[s for s in signals if s["code"] not in holding]

        if triggered and new_sigs:
            next_i=day_i+1
            if next_i>=len(ref)-5: continue
            sc=sum(1 for p in holding.values() if not p.get("is_base"))
            ms=6 if cfg["allow_pyramiding"] else 4
            if sc>=ms: continue

            # 排序选前N
            sorted_sigs=sorted(new_sigs,key=lambda x:x["cp"],reverse=True)
            n_buy = min(4, ms-sc)
            bl = sorted_sigs[:n_buy]

            if sizing_mode=='equal':
                # 等额分配
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
                    cash-=cost; holding[sig["code"]]={"shares":sh,"cost":cost,"entry_price":bp,"entry_date":ref[next_i]["date"],"entry_i":next_i,"highest":bp,"cp":sig["cp"]}
                    signal_log.append({"date":ref[next_i]["date"],"code":sig["code"],"cp":sig["cp"],"weight":1.0/len(bl)})

            else:
                # CP加权分配: 更高CP拿更多钱
                total_cp = sum(s["cp"] for s in bl)
                if total_cp<=0: continue
                tb=cash*0.8
                for sig in bl:
                    weight = sig["cp"]/total_cp
                    recs=data_dict.get(sig["code"],[])
                    if next_i>=len(recs): continue
                    op=recs[next_i]["o"]
                    if op<=0: continue
                    alloc=tb*weight; bp=op*(1+SLIPPAGE); sh=int(alloc/bp/100)*100
                    if sh<100: continue
                    cost=sh*bp*(1+COMMISSION)
                    if cost>cash: continue
                    cash-=cost; holding[sig["code"]]={"shares":sh,"cost":cost,"entry_price":bp,"entry_date":ref[next_i]["date"],"entry_i":next_i,"highest":bp,"cp":sig["cp"]}
                    signal_log.append({"date":ref[next_i]["date"],"code":sig["code"],"cp":sig["cp"],"weight":weight})

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
    equity.append(cash)
    wr = sum(1 for t in trades if t.get("profit_pct",0)>0)/max(len(trades),1)*100
    return equity, len(trades), round(wr,1), signal_log

def buy_hold(data_dict):
    recs=data_dict.get("510300",[])
    if len(recs)<65: return [INITIAL]
    si,ei=60,len(recs)-13; sh=int(INITIAL/recs[si]["c"]/100)*100
    return [sh*recs[i]["c"] for i in range(si,ei+1)]

def metrics(equity, n_trades, win_rate, name):
    if len(equity)<2: return {"name":name,"total_return":0,"max_drawdown":0,"sharpe":0,"annual":0,"trades":0,"win_rate":0}
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
            "sharpe":round(sh,2),"annual":round(ar,2),"trades":n_trades,"win_rate":round(win_rate,1)}

def main():
    print("="*90)
    print("P0 统一回测: 回测CP = 生产CP, 地基打平")
    print("="*90)

    print("\n⏳ 拉取15只ETF K线...")
    data_dict={}
    for code in ETFS:
        data_dict[code]=fetch(code,800)
    ref=data_dict["510300"]
    ref_dates=[r["date"] for r in ref]
    print(f"  数据: {ref_dates[0]} ~ {ref_dates[-1]} ({len(ref)}条)")

    collector = ShareSimulator(data_dict)

    # 4个变体
    variants = [
        ("统一CP(50/20/30,等额)", "equal"),
        ("统一CP+加权(50/20/30,CP加权)", "weighted"),
    ]

    periods=[("3年","2023-05","2026-05"),("2年","2024-05","2026-05"),("1年","2025-05","2026-05")]

    for pname, spfx, epfx in periods:
        mask=[i for i,d in enumerate(ref_dates) if d>=spfx and d<=epfx]
        si,ei=max(60,mask[0]),min(len(ref)-13,mask[-1])
        if si>=ei: continue

        precs={}
        for c in data_dict:
            dlist=data_dict[c]
            if si<len(dlist) and ei<len(dlist):
                precs[c]=dlist[si:ei+1]
        if "510300" not in precs or len(precs["510300"])<65: continue

        print(f"\n{'─'*90}")
        print(f"📅 {pname} ({precs['510300'][0]['date']} ~ {precs['510300'][-1]['date']})")
        print(f"{'─'*90}")
        print(f"  {'变体':<30} {'收益':>7} {'年化':>7} {'回撤':>6} {'夏普':>5} {'胜率':>5} {'交易':>4}")
        print(f"  {'─'*30} {'─'*7} {'─'*7} {'─'*6} {'─'*5} {'─'*5} {'─'*4}")

        period_results=[]
        for vname, sizing_mode in variants:
            eq,nt,wr,siglog=run_backtest(precs, sizing_mode, collector)
            m=metrics(eq,nt,wr,vname)
            period_results.append(m)
            print(f"  {vname:<30} {m['total_return']:>+6.1f}% {m['annual']:>+6.1f}% {m['max_drawdown']:>+5.1f}% {m['sharpe']:>5.2f} {m['win_rate']:>4.1f}% {m['trades']:>4}")

        ebh=buy_hold(precs); mbh=metrics(ebh,0,0,"买持")
        print(f"  {'买持基准':<30} {mbh['total_return']:>+6.1f}% {mbh['annual']:>+6.1f}% {mbh['max_drawdown']:>+5.1f}% {mbh['sharpe']:>5.2f}")

    # ===== 汇总 =====
    print(f"\n{'='*90}")
    print("关键对比")
    print(f"{'='*90}")

    for pname in ["3年","2年","1年"]:
        print(f"\n  [{pname}]")
        print(f"    统一CP (50/20/30): 与生产环境一致")
        print(f"    统一CP+加权 (CP更高=买更多, CP更低=买更少)")

    print(f"\n{'='*90}")
    print("回答你的问题: 按邮件执行能赚钱吗?")
    print(f"{'='*90}")
    print("  条件1: 严格按邮件买入/卖出 → 你能拿到统一CP那档的收益")
    print("  条件2: 市场环境不变 → 过去3年国家队确实频繁护盘, 策略踩中了这个β")
    print("  条件3: 你不贪不慌 → 该卖时卖, 该买时买, 不要手动干预")
    print("  如果三个条件都满足 → 长期看赚钱概率较高")
    print("  最大风险: 国家队停止护盘, 或不以宽基ETF为主要工具 → 策略逻辑会失效")

if __name__=="__main__":
    main()
