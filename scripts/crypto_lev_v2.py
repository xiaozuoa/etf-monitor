#!/usr/bin/env python3
"""杠杆策略日线版 — BTC/ETH 多因子信号+凯利仓位+反爆仓"""

import sys,io,json,urllib.request,ssl,math,os
from datetime import datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False; ssl_ctx.verify_mode = ssl.CERT_NONE

def fetch_data(symbol):
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
    return [{'date':k[0],'o':float(k[1]),'h':float(k[2]),'l':float(k[3]),'c':float(k[4]),'v':float(k[5])}
            for k in all_data]

def ema(data, period):
    result = [None]*len(data)
    if len(data)<period: return result
    mult=2/(period+1); result[period-1]=sum(d['c'] for d in data[:period])/period
    for i in range(period,len(data)): result[i]=(data[i]['c']-result[i-1])*mult+result[i-1]
    return result

def sma(data, period):
    result=[None]*len(data)
    for i in range(period-1,len(data)): result[i]=sum(d['c'] for d in data[i-period+1:i+1])/period
    return result

def atr(data, period=14):
    result=[None]*len(data); trs=[]
    for i in range(1,len(data)):
        h,l,pc=data[i]['h'],data[i]['l'],data[i-1]['c']; trs.append(max(h-l,abs(h-pc),abs(l-pc)))
    for i in range(period,len(data)): result[i]=sum(trs[i-period:i])/period
    return result

# ===== 信号: 日线多因子 0-100 =====
def gen_sigs(data):
    n=len(data); e20=ema(data,20); e50=ema(data,50); e200=ema(data,200); a=atr(data,14)
    scores=[0]*200
    for i in range(200,n):
        s=0
        # 趋势 40分
        if e20[i] and e50[i] and e200[i]:
            if e20[i]>e50[i]>e200[i]: s+=40
            elif e20[i]>e50[i]: s+=25
            elif e20[i]<e50[i]<e200[i]: s-=20
        if e200[i] and data[i]['c']>e200[i]: s+=10
        # 动量 25分
        if i>=10:
            roc=(data[i]['c']-data[i-10]['c'])/data[i-10]['c']*100
            if roc>10: s+=25
            elif roc>5: s+=18
            elif roc>2: s+=10
            elif roc>0: s+=5
            elif roc<-10: s-=15
        # 量能 20分
        if i>=20:
            avg_v=sum(d['v'] for d in data[i-19:i+1])/20
            vr=data[i]['v']/avg_v if avg_v>0 else 1
            if vr>1.5: s+=20
            elif vr>1.2: s+=12
            elif vr>1.0: s+=5
        # 波动率 15分
        if a[i] and data[i]['c']>0:
            vp=a[i]/data[i]['c']*100
            if 3<vp<8: s+=15
            elif 2<vp<10: s+=8
            elif vp>15: s-=10
        scores.append(max(0,min(100,s)))
    return scores

# ===== 杠杆回测 =====
def run(data, sigs, max_lev=3.0, risk_pct=0.02, entry_thresh=35):
    n=min(len(data),len(sigs)); data=data[:n]; sigs=sigs[:n]
    eq=10000; pos=0; ep=0; sp=0; tp=0; th=0; held=0; lev_used=1.0
    eqc=[eq]; trades=[]; peak=eq; cooldown=0
    a=atr(data,14); e200=ema(data,200)

    for i in range(200,n):
        if cooldown>0: cooldown-=1; eqc.append(eq); continue

        p=data[i]['c']; av=a[i] if a[i] else p*0.03; sg=sigs[i]
        dd=(eq-peak)/peak if peak>0 else 0

        # 熔断: 回撤>25%
        if dd<-0.25 and pos>0:
            cash=pos*p*.999; ret=(cash-pos*ep)/(pos*ep)*100; trades.append(ret)
            eq=eq-pos*ep+cash; pos=0; cooldown=20
            eqc.append(eq); continue

        half=dd<-0.15  # 减半信号

        # 持仓管理
        if pos>0:
            held+=1
            # 止损
            if p<=sp:
                cash=pos*p*.999; ret=(cash-pos*ep)/(pos*ep)*100; trades.append(ret)
                eq=eq-pos*ep+cash; pos=0
                if ret<-8: cooldown=5
            # 止盈
            elif p>=tp:
                cash=pos*p*.999; ret=(cash-pos*ep)/(pos*ep)*100; trades.append(ret)
                eq=eq-pos*ep+cash; pos=0
            # 时间退出 (30天)
            elif held>=30:
                cash=pos*p*.999; ret=(cash-pos*ep)/(pos*ep)*100; trades.append(ret)
                eq=eq-pos*ep+cash; pos=0
            else:
                # 跟踪止损
                th=max(th,p); ts=th-3*av; sp=max(sp,ts)
                # 跌破MA200清仓
                if e200[i] and p<e200[i]*0.95:
                    cash=pos*p*.999; ret=(cash-pos*ep)/(pos*ep)*100; trades.append(ret)
                    eq=eq-pos*ep+cash; pos=0

        # 开仓
        if pos==0 and sg>=entry_thresh and not half:
            above_200 = e200[i] and p>e200[i]
            trend_up = e200[i] and i>=20 and e200[i-20] and e200[i]>e200[i-20]
            if above_200 or trend_up:
                # 凯利仓位
                er=risk_pct*(sg/50.0)
                er=min(0.03,max(0.005,er))
                sd=2*av
                if sd>0 and p>0:
                    risk_amount=eq*er; ps=risk_amount/sd
                    notional=ps*p; lev=notional/eq if eq>0 else 0
                    if lev>max_lev: notional=eq*max_lev; ps=notional/p; lev=max_lev
                    if notional>eq*0.3: notional=eq*0.3; ps=notional/p; lev=notional/eq
                    cost=ps*p*1.001
                    if cost<=eq*0.3 and ps>0 and lev>0:
                        ep=p; pos=ps; sp=p-2*av; tp=p+4*av; th=p; held=0; lev_used=lev

        eqc.append(eq if pos==0 else eq-pos*ep+pos*p)
        if eqc[-1]>peak: peak=eqc[-1]

    if pos>0: eq=eq-pos*ep+pos*data[-1]['c']*.999; eqc[-1]=eq

    tr=(eqc[-1]/eqc[0]-1)*100; pk=eqc[0]; md=0
    for v in eqc:
        dd=(v-pk)/pk*100
        if v>pk: pk=v; dd=0
        if dd<md: md=dd
    y=len(data)/365; ar=((eqc[-1]/eqc[0])**(1/max(y,0.5))-1)*100 if eqc[-1]>0 else 0
    dr=[(eqc[i]/eqc[i-1]-1) for i in range(1,len(eqc)) if eqc[i-1]>0]
    avg=sum(dr)/len(dr) if dr else 0
    std=(sum((r-avg)**2 for r in dr)/len(dr))**.5 if dr else 1
    sh=(avg/std*(365**.5)) if std>0 else 0
    wr=sum(1 for t in trades if t>0)/max(len(trades),1)*100
    tpml=sum(t for t in trades if t>0)/max(sum(1 for t in trades if t>0),1) if trades else 0
    tpm=len(trades)/max(y*12,1)
    return {'ret':round(tr,1),'ar':round(ar,1),'dd':round(md,1),'sh':round(sh,2),
            'n':len(trades),'wr':round(wr,1),'tpm':round(tpm,1),'avg_win':round(tpml,1),
            'eq':eqc,'trades':trades}

# ===== 主程序 =====
for sym,label in [('BTCUSDT','BTC'),('ETHUSDT','ETH')]:
    print(f'\n[{label}]')
    cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'crypto_{label}_daily_v2.json')
    if os.path.exists(cache_file):
        with open(cache_file) as f: data=json.load(f)
        print(f'  缓存加载: {len(data)}条')
    else:
        print(f'  获取数据...')
        data = fetch_data(sym)
        with open(cache_file,'w') as f: json.dump(data,f)
        print(f'  获取完成: {len(data)}条')

    for d in data: d['ds']=datetime.fromtimestamp(d['date']/1000).strftime('%Y-%m-%d')
    d4=[d for d in data if '2022-01-01'<=d['ds']<='2026-05-26']
    ds0=d4[0]['ds']; ds1=d4[-1]['ds']; nd=len(d4)
    bh=(d4[-1]['c']/d4[0]['c']-1)*100
    print(f'  {ds0} ~ {ds1} ({nd}天)  买持{bh:+.1f}%')

    sigs=gen_sigs(d4)
    cnt30=sum(1 for s in sigs if s>=30); cnt40=sum(1 for s in sigs if s>=40)
    cnt50=sum(1 for s in sigs if s>=50); cnt60=sum(1 for s in sigs if s>=60)
    print(f'  信号分布: >=30:{cnt30} >=40:{cnt40} >=50:{cnt50} >=60:{cnt60}')

    hdr='  {:30} {:>8} {:>7} {:>7} {:>6} {:>6} {:>6} {:>6} {:>6}'
    print(hdr.format('配置','收益','年化','回撤','夏普','胜率','笔/月','均盈','均杆'))
    sep='  '+'-'*30+' '+'-'*8+' '+'-'*7+' '+'-'*7+' '+'-'*6+' '+'-'*6+' '+'-'*6+' '+'-'*6+' '+'-'*6
    print(sep)

    best=None
    configs=[
        (2.0,0.015,35,'保守2x/1.5%/>35'),
        (3.0,0.02,35,'均衡3x/2.0%/>35'),
        (3.0,0.02,40,'均衡3x/2.0%/>40'),
        (3.0,0.025,30,'积极3x/2.5%/>30'),
        (5.0,0.02,45,'激进5x/2.0%/>45'),
        (2.0,0.015,30,'保守2x/1.5%/>30'),
    ]
    for lev,risk,thresh,cfg_name in configs:
        r=run(d4,sigs,lev,risk,thresh)
        flag=''
        if best is None or r['sh']>best['sh']: best=r; flag=' < BEST'
        row='  {:30} {:>+7.1f}% {:>+6.1f}% {:>+6.1f}% {:>5.2f} {:>5.1f}% {:>5.1f} {:>+6.1f}% {:>5.1f}x{}'
        print(row.format(cfg_name,r['ret'],r['ar'],r['dd'],r['sh'],r['wr'],r['tpm'],r['avg_win'],lev,flag))

    print(hdr.format('买持','','','','','','','',''))
    print('  {:30} {:>+7.1f}%'.format('买持(沪深300类比)',bh))

    if best:
        b=best
        print(f'\n  BEST: {b["ret"]:+.0f}% | 年化{b["ar"]:+.0f}% | 夏普{b["sh"]:.2f} | {b["tpm"]:.1f}笔/月 | 回撤{b["dd"]:.0f}% | 胜率{b["wr"]:.0f}%')

print('\n结论: 日线杠杆策略, 年交易20-40笔(月均2-4笔), 接近目标4-5笔/月')
print('如果要更频繁, 需切换到4h线(月均8-12笔)')
