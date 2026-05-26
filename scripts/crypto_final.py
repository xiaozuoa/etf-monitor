#!/usr/bin/env python3
"""加密货币策略对比 — BTC/ETH 2022-2026 完整四年"""

import sys, io, json, urllib.request, ssl, math
from datetime import datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False; ssl_ctx.verify_mode = ssl.CERT_NONE

def fetch_full(symbol):
    all_data = []
    while True:
        url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit=1000'
        if all_data: url += f'&endTime={all_data[0][0]-1}'
        req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as r:
            raw = json.loads(r.read())
        if not raw or (all_data and raw[-1][0] >= all_data[0][0]): break
        all_data = raw + all_data
        if len(raw) < 1000: break
    return [{'date':k[0],'o':float(k[1]),'h':float(k[2]),'l':float(k[3]),'c':float(k[4]),'v':float(k[5])} for k in all_data]

def ema(data, period):
    result = [None]*len(data)
    if len(data)<period: return result
    mult=2/(period+1)
    result[period-1]=sum(d['c'] for d in data[:period])/period
    for i in range(period,len(data)):
        result[i]=(data[i]['c']-result[i-1])*mult+result[i-1]
    return result

def sma(data, period):
    result=[None]*len(data)
    for i in range(period-1,len(data)):
        result[i]=sum(d['c'] for d in data[i-period+1:i+1])/period
    return result

def atr(data, period=14):
    result=[None]*len(data); trs=[]
    for i in range(1,len(data)):
        h,l,pc=data[i]['h'],data[i]['l'],data[i-1]['c']
        trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    for i in range(period,len(data)):
        result[i]=sum(trs[i-period:i])/period
    return result

def run(data, signals, name):
    n = min(len(data), len(signals))
    data, signals = data[:n], signals[:n]
    cash=10000; h=0; eq=[cash]; ep=0; t_ret=[]
    for i in range(n):
        s=signals[i]; p=data[i]['c']
        if s==1 and h==0:
            qty=cash*.98/p; cost=qty*p*1.001
            if cost<=cash: cash-=cost; h=qty; ep=p
        elif s==-1 and h>0:
            proceeds=h*p*.999; t_ret.append((proceeds-h*ep)/(h*ep)*100)
            cash+=proceeds; h=0
        eq.append(cash+h*p)
    if h>0: cash+=h*data[-1]['c']*.999; eq[-1]=cash

    tr=(eq[-1]/eq[0]-1)*100; peak=eq[0]; mdd=0
    for v in eq:
        dd=(v-peak)/peak*100
        if v>peak: peak=v; dd=0
        if dd<mdd: mdd=dd
    y=len(data)/365; ar=((eq[-1]/eq[0])**(1/max(y,0.5))-1)*100 if eq[-1]>0 else 0
    dr=[(eq[i]/eq[i-1]-1) for i in range(1,len(eq)) if eq[i-1]>0]
    avg=sum(dr)/len(dr) if dr else 0
    std=(sum((r-avg)**2 for r in dr)/len(dr))**.5 if dr else 1
    sh=(avg/std*(365**.5)) if std>0 else 0
    wr=sum(1 for t in t_ret if t>0)/max(len(t_ret),1)*100
    return {'name':name,'ret':round(tr,1),'ar':round(ar,1),'dd':round(mdd,1),'sh':round(sh,2),'n':len(t_ret),'wr':round(wr,1)}

# 策略信号
def sig_atr(data):
    s50=sma(data,50); a=atr(data,14); sig=[0]*50; pos=0; ep=0; ts=0
    for i in range(50,len(data)):
        if s50[i] is None or a[i] is None: sig.append(0); continue
        if pos==0 and data[i]['c']>s50[i]+2*a[i]: sig.append(1); pos=1; ep=data[i]['c']; ts=ep-3*a[i]
        elif pos==1:
            ts=max(ts,data[i]['c']-3*a[i])
            if data[i]['c']<ts or data[i]['c']<s50[i]: sig.append(-1); pos=0
            else: sig.append(0)
        else: sig.append(0)
    return sig[:len(data)]

def sig_triple(data):
    s10,s20,s50=sma(data,10),sma(data,20),sma(data,50); sig=[0]*50; pos=0
    for i in range(50,len(data)):
        if None in(s10[i],s20[i],s50[i],s10[i-1],s20[i-1],s50[i-1]): sig.append(0); continue
        bull=s10[i]>s20[i]>s50[i]; bull_p=s10[i-1]>s20[i-1]>s50[i-1]
        if pos==0 and bull and not bull_p: sig.append(1); pos=1
        elif pos==1 and not bull: sig.append(-1); pos=0
        else: sig.append(0)
    return sig[:len(data)]

def sig_macd(data):
    e12,e26=ema(data,12),ema(data,26)
    dif=[e12[i]-e26[i] if (e12[i] and e26[i]) else None for i in range(len(data))]
    dea=[None]*len(data); start=0
    for i in range(len(data)):
        if dif[i] is not None: start=i; break
    start+=8
    if start>=len(data): return [0]*len(data)
    dea[start]=sum(dif[start-8:start+1])/9; mult=2/10
    for i in range(start+1,len(data)):
        if dif[i] and dea[i-1]: dea[i]=(dif[i]-dea[i-1])*mult+dea[i-1]
    sig=[0]*(start+1); pos=0
    for i in range(start+1,len(data)):
        if not dif[i] or not dea[i]: sig.append(0); continue
        if pos==0 and dif[i]>dea[i] and dif[i-1]<=dea[i-1]: sig.append(1); pos=1
        elif pos==1 and dif[i]<dea[i] and dif[i-1]>=dea[i-1]: sig.append(-1); pos=0
        else: sig.append(0)
    return sig[:len(data)]

def sig_ema(data):
    e20,e50=ema(data,20),ema(data,50); sig=[0]*50; pos=0
    for i in range(50,len(data)):
        if None in (e20[i],e50[i],e20[i-1],e50[i-1]): sig.append(0); continue
        if pos==0 and e20[i]>e50[i] and e20[i-1]<=e50[i-1]: sig.append(1); pos=1
        elif pos==1 and e20[i]<e50[i] and e20[i-1]>=e50[i-1]: sig.append(-1); pos=0
        else: sig.append(0)
    return sig[:len(data)]

def sig_rsi(data):
    result=[None]*len(data); gains,losses=[],[]
    for i in range(1,len(data)):
        diff=data[i]['c']-data[i-1]['c']; gains.append(max(diff,0)); losses.append(max(-diff,0))
    for i in range(14,len(data)):
        avg_g=sum(gains[i-14:i])/14; avg_l=sum(losses[i-14:i])/14
        result[i]=100-(100/(1+avg_g/avg_l)) if avg_l>0 else 100
    sig=[0]*14; pos=0
    for i in range(14,len(data)):
        if result[i] is None: sig.append(0); continue
        if pos==0 and result[i]<30: sig.append(1); pos=1
        elif pos==1 and result[i]>70: sig.append(-1); pos=0
        else: sig.append(0)
    return sig[:len(data)]

def sig_bb(data):
    sig=[0]*20; pos=0
    for i in range(20,len(data)):
        cls=[d['c'] for d in data[i-19:i+1]]; ma=sum(cls)/20
        var=sum((c-ma)**2 for c in cls)/20; std=var**.5
        if pos==0 and data[i]['c']<ma-2*std: sig.append(1); pos=1
        elif pos==1 and data[i]['c']>ma+2*std: sig.append(-1); pos=0
        else: sig.append(0)
    return sig[:len(data)]

all_r = {}
for sym,label in [('BTCUSDT','BTC'),('ETHUSDT','ETH')]:
    print(f'\n[{label}]')
    data = fetch_full(sym)
    for d in data: d['ds']=datetime.fromtimestamp(d['date']/1000).strftime('%Y-%m-%d')
    d4 = [d for d in data if '2022-01-01'<=d['ds']<='2026-05-26']
    print(f'  数据: {d4[0]["ds"]} ~ {d4[-1]["ds"]}  ({len(d4)}天)')
    bh = (d4[-1]['c']/d4[0]['c']-1)*100
    print(f'  BTC买持: {bh:+.1f}%')
    print(f'  {"策略":<14} {"收益":>8} {"年化":>7} {"回撤":>7} {"夏普":>6} {"胜率":>6} {"交易":>5}')
    print(f'  {"-"*14} {"-"*8} {"-"*7} {"-"*7} {"-"*6} {"-"*6} {"-"*5}')
    results=[]
    for sname,sfn in [('ATR趋势',sig_atr),('三均线',sig_triple),('MACD',sig_macd),('EMA20/50',sig_ema),('RSI超卖',sig_rsi),('布林带',sig_bb)]:
        sig = sfn(d4)
        r = run(d4, sig, sname)
        results.append(r)
        print(f'  {sname:<14} {r["ret"]:>+7.1f}% {r["ar"]:>+6.1f}% {r["dd"]:>+6.1f}% {r["sh"]:>5.2f} {r["wr"]:>5.1f}% {r["n"]:>5}')
    all_r[label]=results
    best=sorted(results,key=lambda x:x['sh'],reverse=True)[:3]
    for i,r in enumerate(best,1):
        print(f'  #{i} {r["name"]}: 夏普{r["sh"]} | +{r["ret"]:.0f}% | 回撤{r["dd"]:.0f}% | {r["n"]}笔')

print(f'\n{"="*70}')
print('BTC+ETH 综合夏普排名')
print(f'{"="*70}')
combined={}
for name in ['ATR趋势','三均线','MACD','EMA20/50','RSI超卖','布林带']:
    scores=[]
    for sym_data in all_r.values():
        for r in sym_data:
            if r['name']==name: scores.append(r['sh'])
    if len(scores)==2:
        combined[name]=(scores[0]+scores[1])/2
for rank,(name,avg_sh) in enumerate(sorted(combined.items(),key=lambda x:x[1],reverse=True),1):
    r_btc=[r for r in all_r['BTC'] if r['name']==name][0]
    r_eth=[r for r in all_r['ETH'] if r['name']==name][0]
    print(f'  #{rank} {name}: 夏普{avg_sh:.2f} | BTC{r_btc["ret"]:+.0f}% ETH{r_eth["ret"]:+.0f}% | {r_btc["n"]+r_eth["n"]}笔({r_btc["n"]+r_eth["n"]}年均{r_btc["n"]+r_eth["n"]//4})')
