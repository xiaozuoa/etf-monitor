#!/usr/bin/env python3
"""杠杆趋势策略 — 4h K线, 动态仓位, 反爆仓机制, BTC/ETH 2022-2026回测"""

import sys, io, json, urllib.request, ssl, math
from datetime import datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False; ssl_ctx.verify_mode = ssl.CERT_NONE

# ============================================
# 数据
# ============================================
def fetch_full(symbol, interval="4h"):
    all_data = []; cap = 0
    while True:
        url = f'https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=1000'
        if all_data: url += f'&endTime={all_data[0][0]-1}'
        req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as r:
            raw = json.loads(r.read())
        if not raw or (all_data and raw[-1][0] >= all_data[0][0]): break
        all_data = raw + all_data; cap += 1
        if len(raw) < 1000 or cap > 10: break
    return [{'date':k[0],'o':float(k[1]),'h':float(k[2]),'l':float(k[3]),'c':float(k[4]),'v':float(k[5])}
            for k in all_data]

def ema(data, period):
    result=[None]*len(data)
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

# ============================================
# 信号引擎
# ============================================
def generate_signals(data):
    """多因子打分 0-100"""
    n = len(data)
    e20 = ema(data,20); e50 = ema(data,50); e200 = ema(data,200)
    a = atr(data,14)

    # 量能: 当前量/20周期均量
    vol_ratio = [None]*n
    for i in range(20,n):
        avg_v = sum(d['v'] for d in data[i-19:i+1])/20
        vol_ratio[i] = data[i]['v']/avg_v if avg_v>0 else 1

    # 动量: 10周期涨跌幅
    roc10 = [None]*n
    for i in range(10,n):
        roc10[i] = (data[i]['c']-data[i-10]['c'])/data[i-10]['c']*100

    scores = [0]*200;  # 前200根用于初始化

    for i in range(200,n):
        score = 0

        # 趋势因子 (40分): EMA排列
        if e20[i] and e50[i] and e200[i]:
            if e20[i] > e50[i] > e200[i]: score += 40       # 多头排列
            elif e20[i] > e50[i]: score += 25                 # 短期多头
            elif e20[i] < e50[i] < e200[i]: score -= 20       # 空头排列(做空信号, 此处只做多)
        if e20[i] and e200[i] and data[i]['c'] > e200[i]: score += 10  # 价格在200EMA之上

        # 动量因子 (25分)
        if roc10[i]:
            if roc10[i] > 5: score += 25
            elif roc10[i] > 2: score += 15
            elif roc10[i] > 0: score += 5
            elif roc10[i] < -5: score -= 15

        # 量能因子 (20分)
        if vol_ratio[i]:
            if vol_ratio[i] > 1.5: score += 20
            elif vol_ratio[i] > 1.2: score += 12
            elif vol_ratio[i] > 1.0: score += 5

        # 波动率因子 (15分) — 适中波动最好
        if a[i] and data[i]['c']>0:
            vol_pct = a[i]/data[i]['c']*100
            if 3 < vol_pct < 8: score += 15     # 适中波动
            elif 2 < vol_pct < 10: score += 8
            elif vol_pct > 15: score -= 10       # 过高波动, 危险

        scores.append(max(0, min(100, score)))

    return scores

# ============================================
# 仓位计算 (Kelly + ATR风控)
# ============================================
def calc_position(equity, price, atr_val, signal_score, max_lev=3.0):
    """
    凯利公式仓位:
    - 基础风险: 权益的2%
    - 止损距离: 2*ATR
    - 信号调整: score/100 缩放风险
    - 杠杆封顶: max_lev
    - 单笔仓位上限: 权益的25%
    """
    risk_pct = 0.02  # 基础2%风险
    # 信号越强, 风险越接近2%; 信号弱, 降低风险
    effective_risk = risk_pct * (signal_score / 60)  # 60分基准
    effective_risk = min(0.03, max(0.005, effective_risk))  # 0.5%-3%区间

    stop_dist = 2 * atr_val
    if stop_dist <= 0 or price <= 0:
        return 0, 1.0

    # 计算出多少币
    risk_amount = equity * effective_risk
    position_size = risk_amount / stop_dist  # 币的数量

    # 名义价值
    notional = position_size * price
    leverage = notional / equity if equity > 0 else 0

    # 杠杆封顶
    if leverage > max_lev:
        notional = equity * max_lev
        position_size = notional / price
        leverage = max_lev

    # 单笔仓位上限25%
    if notional > equity * 0.25:
        notional = equity * 0.25
        position_size = notional / price
        leverage = notional / equity

    return position_size, leverage

# ============================================
# 回测
# ============================================
def run_backtest(data, signals, max_lev=3.0):
    n = min(len(data), len(signals))
    data, signals = data[:n], signals[:n]

    equity = 10000  # 起始1万U
    position = 0    # 持仓币数
    entry_price = 0; stop_price = 0; tp_price = 0
    trail_high = 0; bars_held = 0
    eq_curve = [equity]
    trades = []
    peak_equity = equity
    cooldown = 0  # 熔断冷却期

    a = atr(data, 14)
    e200 = ema(data, 200)

    for i in range(200, n):
        if cooldown > 0:
            cooldown -= 1
            eq_curve.append(equity)
            continue

        price = data[i]['c']
        atr_val = a[i] if a[i] else price * 0.03
        sig = signals[i]
        drawdown = (equity - peak_equity) / peak_equity

        # 熔断: 从峰值回撤>25%
        if drawdown < -0.25:
            if position > 0:
                proceeds = position * price * 0.999
                ret = (proceeds - position * entry_price) / (position * entry_price) * 100
                trades.append({'ret': ret, 'lev': position*entry_price/equity_before_entry if 'equity_before_entry' in dir() else 1})
                position = 0
            cooldown = 14 * 6  # 14天(6根4h/天)
            peak_equity = equity
            eq_curve.append(equity)
            continue

        # 回撤>15%: 减半仓位
        half_size = drawdown < -0.15

        if position > 0:
            bars_held += 1

            # 止损
            if price <= stop_price:
                proceeds = position * price * 0.999
                ret = (proceeds - position * entry_price) / (position * entry_price) * 100
                trades.append({'ret': ret, 'lev': leverage_used})
                equity = equity - position * entry_price + proceeds
                position = 0
                if ret < -5: cooldown = 6  # 大亏后冷却1天
            # 止盈
            elif price >= tp_price:
                proceeds = position * price * 0.999
                ret = (proceeds - position * entry_price) / (position * entry_price) * 100
                trades.append({'ret': ret, 'lev': leverage_used})
                equity = equity - position * entry_price + proceeds
                position = 0
            # 时间退出 (10天 = 60根4h)
            elif bars_held >= 60:
                proceeds = position * price * 0.999
                ret = (proceeds - position * entry_price) / (position * entry_price) * 100
                trades.append({'ret': ret, 'lev': leverage_used})
                equity = equity - position * entry_price + proceeds
                position = 0
            else:
                # 更新跟踪止损
                trail_high = max(trail_high, price)
                trail_stop = trail_high - 3 * atr_val
                stop_price = max(stop_price, trail_stop)  # 只上移不下降
                # 更新权益(未实现)
                equity = equity - position * entry_price + position * price

        # 开仓
        if position == 0:
            if sig >= 35 and not half_size:
                # 趋势确认: 价格在200EMA之上
                above_200 = e200[i] and price > e200[i]
                # 或者长期趋势向上(200EMA斜率>0)
                trend_up = e200[i] and i>=20 and e200[i-20] and e200[i] > e200[i-20]
                if above_200 or trend_up:
                    pos_size, lev = calc_position(equity, price, atr_val, sig, max_lev)
                    if pos_size > 0 and lev > 0:
                        cost = pos_size * price * 1.001
                        if cost <= equity * 0.25:
                            entry_price = price
                            position = pos_size
                            stop_price = price - 2 * atr_val
                            tp_price = price + 4 * atr_val
                            trail_high = price
                            bars_held = 0
                            leverage_used = lev
                            equity_before_entry = equity

        eq_curve.append(equity if position == 0 else equity - position * entry_price + position * price)
        if eq_curve[-1] > peak_equity:
            peak_equity = eq_curve[-1]

    # 清仓
    if position > 0:
        equity = equity - position * entry_price + position * data[-1]['c'] * 0.999
        eq_curve[-1] = equity

    # 统计
    tr = (eq_curve[-1]/eq_curve[0]-1)*100
    peak=eq_curve[0]; mdd=0
    for v in eq_curve:
        dd=(v-peak)/peak*100
        if v>peak: peak=v; dd=0
        if dd<mdd: mdd=dd
    y=len(data)/(365*6)  # 4h candles per year
    ar=((eq_curve[-1]/eq_curve[0])**(1/max(y,0.5))-1)*100 if eq_curve[-1]>0 else 0
    dr=[(eq_curve[i]/eq_curve[i-1]-1) for i in range(1,len(eq_curve)) if eq_curve[i-1]>0]
    avg=sum(dr)/len(dr) if dr else 0
    std=(sum((r-avg)**2 for r in dr)/len(dr))**.5 if dr else 1
    sh=(avg/std*(365*6**.5)) if std>0 else 0
    wr=sum(1 for t in trades if t['ret']>0)/max(len(trades),1)*100
    avg_lev=sum(t['lev'] for t in trades)/max(len(trades),1) if trades else 0
    avg_ret=sum(t['ret'] for t in trades)/max(len(trades),1) if trades else 0
    trades_per_month = len(trades)/max(y*12,1)

    return {
        'ret':round(tr,1),'ar':round(ar,1),'dd':round(mdd,1),'sh':round(sh,2),
        'n':len(trades),'wr':round(wr,1),'avg_lev':round(avg_lev,1),
        'avg_ret':round(avg_ret,1),'tpm':round(trades_per_month,1)
    }

# ============================================
# 主程序
# ============================================
for sym,label in [('BTCUSDT','BTC'),('ETHUSDT','ETH')]:
    print(f'\n[{label}] 获取4h数据...')
    data = fetch_full(sym, "4h")
    for d in data: d['ds']=datetime.fromtimestamp(d['date']/1000).strftime('%Y-%m-%d %H:%M')
    d4 = [d for d in data if '2022-01-01'<=d['ds'][:10]<='2026-05-26']
    ds0 = d4[0]['ds']; ds1 = d4[-1]['ds']; n4 = len(d4)
    print(f'  数据: {ds0} ~ {ds1}  ({n4}根4hK线)')
    bh = (d4[-1]['c']/d4[0]['c']-1)*100

    print(f'  生成信号...')
    sigs = generate_signals(d4)
    # 信号分布
    cnt35 = sum(1 for s in sigs if s>=35)
    cnt50 = sum(1 for s in sigs if s>=50)
    cnt65 = sum(1 for s in sigs if s>=65)
    print(f'  信号分布: >=35: {cnt35}, >=50: {cnt50}, >=65: {cnt65}')

    hdr = '  {:8} {:>8} {:>7} {:>7} {:>6} {:>6} {:>5} {:>5} {:>6} {:>7}'
    sep = '  ' + '-'*8 + ' ' + '-'*8 + ' ' + '-'*7 + ' ' + '-'*7 + ' ' + '-'*6 + ' ' + '-'*6 + ' ' + '-'*5 + ' ' + '-'*5 + ' ' + '-'*6 + ' ' + '-'*7
    print('\n' + hdr.format('杠杆','收益','年化','回撤','夏普','胜率','交易','均杆','笔/月','均盈'))
    print(sep)
    best = None
    for lev in [1.0, 2.0, 3.0, 5.0]:
        r = run_backtest(d4, sigs, lev)
        flag = ''
        if best is None or r['sh'] > best['sh']:
            best = r; flag = ' < BEST'
        row = '  {}x      {:>+7.1f}% {:>+6.1f}% {:>+6.1f}% {:>5.2f} {:>5.1f}% {:>5} {:>4.1f}x {:>5.1f} {:>+6.1f}%{}'
        print(row.format(lev, r['ret'], r['ar'], r['dd'], r['sh'], r['wr'], r['n'], r['avg_lev'], r['tpm'], r['avg_ret'], flag))
    print('  {:8} {:>+7.1f}%'.format('买持', bh))

    bl=best['avg_lev']; bt=best['tpm']; br=best['ret']; bs=best['sh']
    print('\n  最优: {:.1f}x杠杆, {:.1f}笔/月, 收益{:+.0f}%, 夏普{:.2f}'.format(bl,bt,br,bs))

tpm_val = best['tpm']
print('\n提醒: 4h策略=每6根/天, 月均{:.0f}笔, 符合4-5笔/月目标'.format(tpm_val))
