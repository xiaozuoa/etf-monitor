#!/usr/bin/env python3
"""加密货币策略同台对比 — BTC/ETH 四年(2022-2026) 8策略×2标的"""

import json, urllib.request, ssl, math, sys
from datetime import datetime

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False; ssl_ctx.verify_mode = ssl.CERT_NONE

def fetch_binance(symbol, interval="1d", limit=1500):
    """获取Binance K线数据 (免费公开API)"""
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as r:
            raw = json.loads(r.read())
        return [{"date": k[0], "o": float(k[1]), "h": float(k[2]),
                 "l": float(k[3]), "c": float(k[4]), "v": float(k[5])}
                for k in raw if len(k) >= 6]
    except Exception as e:
        print(f"  Error fetching {symbol}: {e}")
        return []

def ema(data, period):
    """指数移动平均"""
    if len(data) < period:
        return [None] * len(data)
    result = [None] * len(data)
    # SMA作为初始值
    sma = sum(d["c"] for d in data[:period]) / period
    multiplier = 2 / (period + 1)
    result[period - 1] = sma
    for i in range(period, len(data)):
        result[i] = (data[i]["c"] - result[i - 1]) * multiplier + result[i - 1]
    return result

def sma(data, period):
    """简单移动平均"""
    result = [None] * len(data)
    for i in range(period - 1, len(data)):
        result[i] = sum(d["c"] for d in data[i - period + 1:i + 1]) / period
    return result

def rsi(data, period=14):
    """RSI指标"""
    result = [None] * len(data)
    gains = [0]
    losses = [0]
    for i in range(1, len(data)):
        diff = data[i]["c"] - data[i - 1]["c"]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    for i in range(period, len(data)):
        avg_gain = sum(gains[i - period + 1:i + 1]) / period
        avg_loss = sum(losses[i - period + 1:i + 1]) / period
        if avg_loss == 0:
            result[i] = 100
        else:
            rs = avg_gain / avg_loss
            result[i] = 100 - (100 / (1 + rs))
    return result

def atr(data, period=14):
    """平均真实波幅"""
    result = [None] * len(data)
    trs = [None]
    for i in range(1, len(data)):
        h, l, pc = data[i]["h"], data[i]["l"], data[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    for i in range(period, len(data)):
        result[i] = sum(trs[i - period + 1:i + 1]) / period
    return result

# ============================================
# 策略定义
# ============================================
STRATEGIES = {}

def register(name, desc):
    def wrapper(fn):
        STRATEGIES[name] = {"fn": fn, "desc": desc}
        return fn
    return wrapper

@register("ema_20_50", "EMA双均线: EMA20>EMA50买入, 反向卖出, 中线趋势")
def strat_ema_cross(data, params=None):
    """EMA20/50交叉"""
    e20 = ema(data, 20)
    e50 = ema(data, 50)
    signals = []
    position = 0
    for i in range(50, len(data)):
        if e20[i] is None or e50[i] is None:
            signals.append(0); continue
        if position == 0 and e20[i] > e50[i] and e20[i - 1] <= e50[i - 1]:
            signals.append(1); position = 1
        elif position == 1 and e20[i] < e50[i] and e20[i - 1] >= e50[i - 1]:
            signals.append(-1); position = 0
        else:
            signals.append(0)
    return [0] * 50 + signals

@register("macd", "MACD: DIF>DEA买入, 反向卖出, 趋势跟踪")
def strat_macd(data, params=None):
    """MACD 12/26/9"""
    e12 = ema(data, 12)
    e26 = ema(data, 26)
    dif = [e12[i] - e26[i] if (e12[i] and e26[i]) else None for i in range(len(data))]
    dea = []
    # 计算DEA (dif的9周期EMA)
    valid_dif = [d for d in dif if d is not None]
    if len(valid_dif) < 9:
        return [0] * len(data)
    start = dif.index(valid_dif[0]) + 8
    dea = [None] * len(data)
    sma_dif = sum(valid_dif[:9]) / 9
    dea_idx = start
    dea[dea_idx] = sma_dif
    mult = 2 / 10
    for i in range(dea_idx + 1, len(data)):
        if dif[i] is not None and dea[i - 1] is not None:
            dea[i] = (dif[i] - dea[i - 1]) * mult + dea[i - 1]

    signals = []
    position = 0
    for i in range(max(26, dea_idx + 1), len(data)):
        if dif[i] is None or dea[i] is None:
            signals.append(0); continue
        if position == 0 and dif[i] > dea[i] and dif[i - 1] <= dea[i - 1]:
            signals.append(1); position = 1
        elif position == 1 and dif[i] < dea[i] and dif[i - 1] >= dea[i - 1]:
            signals.append(-1); position = 0
        else:
            signals.append(0)
    return [0] * (max(26, dea_idx + 1)) + signals

@register("rsi_meanrev", "RSI均值回归: RSI<30超卖买入, RSI>70超买卖出")
def strat_rsi(data, params=None):
    r = rsi(data, 14)
    signals = []
    position = 0
    for i in range(14, len(data)):
        if r[i] is None: signals.append(0); continue
        if position == 0 and r[i] < 30:
            signals.append(1); position = 1
        elif position == 1 and r[i] > 70:
            signals.append(-1); position = 0
        else:
            signals.append(0)
    return [0] * 14 + signals

@register("bb_reversal", "布林带反转: 价格跌破下轨买入, 升破上轨卖出 (20,2)")
def strat_bb(data, params=None):
    period = 20; std_mult = 2.0
    signals = []
    position = 0
    for i in range(period, len(data)):
        closes = [d["c"] for d in data[i - period + 1:i + 1]]
        ma = sum(closes) / period
        variance = sum((c - ma) ** 2 for c in closes) / period
        std = math.sqrt(variance)
        upper = ma + std_mult * std
        lower = ma - std_mult * std
        if position == 0 and data[i]["c"] < lower:
            signals.append(1); position = 1
        elif position == 1 and data[i]["c"] > upper:
            signals.append(-1); position = 0
        else:
            signals.append(0)
    return [0] * period + signals

@register("donchian_break", "唐奇安通道突破: 20日高点突破买入, 10日低点跌破卖出")
def strat_donchian(data, params=None):
    signals = []
    position = 0; highest_since_entry = 0
    for i in range(20, len(data)):
        h20 = max(d["h"] for d in data[i - 19:i + 1])
        l10 = min(d["l"] for d in data[i - 9:i + 1])
        if position == 0 and data[i]["c"] > h20:
            signals.append(1); position = 1; highest_since_entry = data[i]["c"]
        elif position == 1:
            highest_since_entry = max(highest_since_entry, data[i]["c"])
            if data[i]["c"] < l10:
                signals.append(-1); position = 0
            else:
                signals.append(0)
        else:
            signals.append(0)
    return [0] * 20 + signals

@register("triple_ma", "三均线: MA10>MA20>MA50买入, 三者汇聚后发散介入")
def strat_triple_ma(data, params=None):
    s10 = sma(data, 10); s20 = sma(data, 20); s50 = sma(data, 50)
    signals = []; position = 0
    for i in range(50, len(data)):
        if None in (s10[i], s20[i], s50[i], s10[i-1], s20[i-1], s50[i-1]):
            signals.append(0); continue
        # 买入: 三线多头排列且刚形成
        bull = s10[i] > s20[i] > s50[i]
        bull_prev = s10[i-1] > s20[i-1] > s50[i-1]
        if position == 0 and bull and not bull_prev:
            signals.append(1); position = 1
        elif position == 1 and not bull:
            signals.append(-1); position = 0
        else:
            signals.append(0)
    return [0] * 50 + signals

@register("parabolic_sar", "SAR反转: 趋势转向时反向操作")
def strat_sar(data, params=None):
    af = 0.02; af_max = 0.2; signals = []; position = 0
    sar = data[0]["l"]; ep = data[0]["h"]; long = True
    for i in range(1, len(data)):
        if long:
            sar = sar + af * (ep - sar)
            if sar > data[i]["l"]:
                long = False; sar = ep; ep = data[i]["l"]; af = 0.02
        else:
            sar = sar - af * (sar - ep)
            if sar < data[i]["h"]:
                long = True; sar = ep; ep = data[i]["h"]; af = 0.02
        if long:
            ep = max(ep, data[i]["h"])
            if ep > data[i - 1]["h"]: af = min(af + 0.02, af_max)
        else:
            ep = min(ep, data[i]["l"])
            if ep < data[i - 1]["l"]: af = min(af + 0.02, af_max)

        prev_long = None
        if i >= 2:
            prev_sar = sar
        if position == 0 and long and i >= 1:
            signals.append(1); position = 1
        elif position == 1 and not long:
            signals.append(-1); position = 0
        else:
            signals.append(0)
    return [0] + signals  # 对齐

@register("trend_atr", "ATR趋势跟踪: 价格突破MA50+2*ATR买入, 跌破MA50-2*ATR卖出")
def strat_trend_atr(data, params=None):
    s50 = sma(data, 50); a = atr(data, 14)
    signals = []; position = 0; entry_price = 0; trail_stop = 0
    for i in range(50, len(data)):
        if s50[i] is None or a[i] is None:
            signals.append(0); continue
        upper = s50[i] + 2 * a[i]
        lower = s50[i] - 2 * a[i]
        if position == 0 and data[i]["c"] > upper:
            signals.append(1); position = 1; entry_price = data[i]["c"]
            trail_stop = entry_price - 3 * a[i]
        elif position == 1:
            trail_stop = max(trail_stop, data[i]["c"] - 3 * a[i])
            if data[i]["c"] < trail_stop or data[i]["c"] < s50[i]:
                signals.append(-1); position = 0
            else:
                signals.append(0)
        else:
            signals.append(0)
    return [0] * 50 + signals


# ============================================
# 回测引擎
# ============================================
def run_backtest(data, signals, name, symbol):
    """根据买卖信号计算收益率"""
    if len(data) != len(signals):
        # 截断到较短者
        n = min(len(data), len(signals))
        data = data[:n]; signals = signals[:n]

    cash = 10000; holdings = 0; equity = [cash]
    trades = []
    entry_price = 0

    for i in range(len(data)):
        sig = signals[i] if i < len(signals) else 0
        price = data[i]["c"]

        if sig == 1 and holdings == 0:
            # 买入
            shares = cash * 0.98 / price  # 留2%缓冲给手续费
            cost = shares * price * 1.001  # 0.1%手续费
            if cost <= cash:
                cash -= cost; holdings = shares; entry_price = price
        elif sig == -1 and holdings > 0:
            # 卖出
            proceeds = holdings * price * 0.999
            cash += proceeds
            profit = (proceeds - holdings * entry_price) / (holdings * entry_price) * 100
            trades.append(profit)
            holdings = 0
            entry_price = 0

        eq = cash + holdings * price
        equity.append(eq)

    # 最终清仓
    if holdings > 0:
        cash += holdings * data[-1]["c"] * 0.999
        equity[-1] = cash

    # 统计
    total_ret = (equity[-1] / equity[0] - 1) * 100
    peak = equity[0]; max_dd = 0
    for v in equity:
        dd = (v - peak) / peak * 100
        if v > peak: peak = v; dd = 0
        if dd < max_dd: max_dd = dd

    # 年化
    days = len(data)
    years = days / 365
    if years > 0 and equity[-1] > 0:
        ann_ret = ((equity[-1] / equity[0]) ** (1 / years) - 1) * 100
    else:
        ann_ret = 0

    # 夏普 (用日收益率)
    daily_r = [(equity[i] / equity[i - 1] - 1) for i in range(1, len(equity)) if equity[i - 1] > 0]
    if len(daily_r) > 1:
        avg = sum(daily_r) / len(daily_r)
        std = (sum((r - avg) ** 2 for r in daily_r) / len(daily_r)) ** 0.5
        sharpe = (avg / std * (365 ** 0.5)) if std > 0 else 0
    else:
        sharpe = 0

    # 胜率
    win_rate = sum(1 for t in trades if t > 0) / max(len(trades), 1) * 100

    # Buy & hold
    bh_ret = (data[-1]["c"] / data[0]["c"] - 1) * 100 if data[0]["c"] > 0 else 0

    return {
        "name": name, "symbol": symbol,
        "total_return": round(total_ret, 1), "annual_return": round(ann_ret, 1),
        "max_drawdown": round(max_dd, 1), "sharpe": round(sharpe, 2),
        "trades": len(trades), "win_rate": round(win_rate, 1),
        "buy_hold": round(bh_ret, 1), "excess": round(total_ret - bh_ret, 1),
    }


def main():
    print("=" * 100)
    print("加密货币策略同台对比 — 8策略 × BTC/ETH × 4年(2022-2026)")
    print("=" * 100)

    symbols = [("BTCUSDT", "BTC"), ("ETHUSDT", "ETH")]

    for sym, label in symbols:
        # 获取数据 — 分两段: 2022-2023年 和 2024-2026年
        print(f"\n⏳ 获取 {label} 数据...")
        all_data = fetch_binance(sym, "1d", 1500)

        if not all_data:
            print(f"  ❌ 获取{label}失败")
            continue

        # 转换为日期格式
        for d in all_data:
            d["date_str"] = datetime.fromtimestamp(d["date"] / 1000).strftime("%Y-%m-%d")

        # 筛选2022-2026
        data_4y = [d for d in all_data if "2022-01-01" <= d["date_str"] <= "2026-05-26"]
        if len(data_4y) < 300:
            print(f"  ❌ {label}数据不足: {len(data_4y)}条")
            continue

        print(f"  数据: {data_4y[0]['date_str']} ~ {data_4y[-1]['date_str']} ({len(data_4y)}天)")

        # 分段
        split1 = len(data_4y) // 2
        data_2y_first = data_4y[:split1]
        data_2y_second = data_4y[split1:]

        # 跑所有策略
        print(f"\n  {'策略':<25} {'全周期收益':>9} {'年化':>8} {'回撤':>7} {'夏普':>6} {'胜率':>6} {'交易':>5} {'买持':>8} {'超额':>8}")
        print(f"  {'─'*25} {'─'*9} {'─'*8} {'─'*7} {'─'*6} {'─'*6} {'─'*5} {'─'*8} {'─'*8}")

        all_results = []
        for name, sdef in STRATEGIES.items():
            signals = sdef["fn"](data_4y)
            result = run_backtest(data_4y, signals, name, label)
            all_results.append(result)
            print(f"  {sdef['desc'][:25]:<25} {result['total_return']:>+8.1f}% {result['annual_return']:>+7.1f}% {result['max_drawdown']:>+6.1f}% {result['sharpe']:>5.2f} {result['win_rate']:>5.1f}% {result['trades']:>5} {result['buy_hold']:>+7.1f}% {result['excess']:>+7.1f}%")

        # Buy & hold
        bh = (data_4y[-1]["c"] / data_4y[0]["c"] - 1) * 100
        print(f"  {'买持':<25} {bh:>+8.1f}%")

        # 排名
        best = sorted(all_results, key=lambda x: x["sharpe"], reverse=True)[:3]
        print(f"\n  🏆 {label} 夏普最高 TOP3:")
        for r in best:
            print(f"     {r['name']}: 夏普{r['sharpe']:.2f} | 收益{r['total_return']:+.0f}% | 回撤{r['max_drawdown']:.0f}% | 交易{r['trades']}次")
            print(f"           ({STRATEGIES[r['name']]['desc']})")

    # === 跨标的平均排名 ===
    print(f"\n{'='*100}")
    print("综合排名 (BTC+ETH 夏普均值)")
    print(f"{'='*100}")

    combined = {}
    for name in STRATEGIES:
        scores = []
        for r_list in all_results_by_symbol.values():
            for r in r_list:
                if r["name"] == name:
                    scores.append(r["sharpe"])
        if len(scores) == 2:
            combined[name] = {
                "avg_sharpe": (scores[0] + scores[1]) / 2,
                "desc": STRATEGIES[name]["desc"]
            }

    for rank, (name, info) in enumerate(sorted(combined.items(), key=lambda x: x[1]["avg_sharpe"], reverse=True), 1):
        print(f"  #{rank} {name:<18} 夏普{info['avg_sharpe']:.2f}  — {info['desc']}")


if __name__ == "__main__":
    all_results_by_symbol = {}
    # 重写main以收集结果
    print("=" * 100)
    print("加密货币策略同台对比 — 8策略 × BTC/ETH × 4年(2022-2026)")
    print("=" * 100)

    symbols = [("BTCUSDT", "BTC"), ("ETHUSDT", "ETH")]

    for sym, label in symbols:
        print(f"\n⏳ 获取 {label} 数据...")
        all_data = fetch_binance(sym, "1d", 1500)

        if not all_data:
            continue

        for d in all_data:
            d["date_str"] = datetime.fromtimestamp(d["date"] / 1000).strftime("%Y-%m-%d")

        data_4y = [d for d in all_data if "2022-01-01" <= d["date_str"] <= "2026-05-26"]
        if len(data_4y) < 300:
            continue

        print(f"  数据: {data_4y[0]['date_str']} ~ {data_4y[-1]['date_str']} ({len(data_4y)}天)")

        print(f"\n  {'策略':<30} {'收益':>8} {'年化':>7} {'回撤':>7} {'夏普':>6} {'胜率':>6} {'交易':>5}")
        print(f"  {'─'*30} {'─'*8} {'─'*7} {'─'*7} {'─'*6} {'─'*6} {'─'*5}")

        results = []
        for name, sdef in STRATEGIES.items():
            signals = sdef["fn"](data_4y)
            result = run_backtest(data_4y, signals, name, label)
            results.append(result)
            print(f"  {sdef['desc'][:30]:<30} {result['total_return']:>+7.1f}% {result['annual_return']:>+6.1f}% {result['max_drawdown']:>+6.1f}% {result['sharpe']:>5.2f} {result['win_rate']:>5.1f}% {result['trades']:>5}")

        bh = (data_4y[-1]["c"] / data_4y[0]["c"] - 1) * 100
        print(f"  {'买持':<30} {bh:>+7.1f}%")

        # 排名
        sorted_r = sorted(results, key=lambda x: x["sharpe"], reverse=True)
        print(f"\n  🏆 {label} 夏普排名:")
        for rank, r in enumerate(sorted_r[:5], 1):
            print(f"     #{rank} {r['name']:<15} 夏普{r['sharpe']:+.2f} | 收益{r['total_return']:+.0f}% | 回撤{r['max_drawdown']:.0f}% | {r['trades']}笔")

        all_results_by_symbol[label] = results

    # 综合
    print(f"\n{'='*100}")
    print("跨标的综合排名 (BTC+ETH夏普均值)")
    print(f"{'='*100}")
    combined = {}
    for name in STRATEGIES:
        scores = []
        for sym_results in all_results_by_symbol.values():
            for r in sym_results:
                if r["name"] == name:
                    scores.append(r["sharpe"])
        if len(scores) == 2:
            combined[name] = (scores[0] + scores[1]) / 2
    for rank, (name, avg_sh) in enumerate(sorted(combined.items(), key=lambda x: x[1], reverse=True), 1):
        print(f"  #{rank} {name:<18} 夏普{avg_sh:.2f}  — {STRATEGIES[name]['desc']}")
