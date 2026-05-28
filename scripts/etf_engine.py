#!/usr/bin/env python3
"""
ETF三因子引擎 v3 — 7项策略改进
  ① 新浪实时行情(盘中分时)  ② 盘后真实份额确认
  ③ 相对强弱因子(区分普涨)  ④ 连续日确认(过滤一日游)
  ⑤ ATR动态止损止盈          ⑥ 北向资金+宏观背景
  ⑦ 数据驱动权重优化
"""

import json, urllib.request, ssl, os, sys, io, math
from datetime import datetime, timedelta
from collections import defaultdict

if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# 复用主脚本的K线fetch
from etf_signals import fetch as _fetch_kline, calc_rs, detect_trend, compute_cp

ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

WORKSPACE = os.path.expanduser("~/.etf-skill/workspace")
os.makedirs(WORKSPACE, exist_ok=True)

# ---- ETF池 ----
ETFS = {
    # === 宽基(10只) — 国家队主战场 ===
    "510300": {"n": "华泰柏瑞沪深300ETF", "idx": "沪深300",  "market": "sh"},
    "510050": {"n": "华夏上证50ETF",      "idx": "上证50",   "market": "sh"},
    "510500": {"n": "华泰柏瑞中证500ETF", "idx": "中证500",  "market": "sh"},
    "512100": {"n": "南方中证1000ETF",    "idx": "中证1000", "market": "sh"},
    "588000": {"n": "华夏科创50ETF",      "idx": "科创50",   "market": "sh"},
    "159915": {"n": "易方达创业板ETF",    "idx": "创业板",   "market": "sz"},
    "563360": {"n": "华泰柏瑞A500ETF",    "idx": "A500",    "market": "sh"},
    "510210": {"n": "富国上证综指ETF",    "idx": "上证综指", "market": "sh"},
    "159967": {"n": "华夏创业板成长ETF",  "idx": "创业板成长","market": "sz"},
    "159995": {"n": "华夏芯片ETF",        "idx": "芯片",     "market": "sz"},
    # === 防御+主题(5只) — 国家队新方向 ===
    "510880": {"n": "华泰柏瑞红利ETF",    "idx": "红利",     "market": "sh"},
    "512660": {"n": "国泰军工ETF",        "idx": "军工",     "market": "sh"},
    "512010": {"n": "华宝医药ETF",        "idx": "医药",     "market": "sh"},
    "588200": {"n": "华夏科创芯片ETF",    "idx": "科创芯片", "market": "sh"},
    "159819": {"n": "易方达人工智能ETF",  "idx": "人工智能", "market": "sz"},
}


# ================================================================
# ① 实时行情 (新浪 — 盘中可用, Free, No Key)
# ================================================================

def fetch_realtime(codes=None):
    """获取ETF实时行情。
    返回: {code: {price, open, prev_close, high, low, volume, amount, change_pct, time}}
    """
    if codes is None:
        codes = list(ETFS.keys())

    sina_codes = [f"{ETFS[c]['market']}{c}" for c in codes]
    url = "http://hq.sinajs.cn/list=" + ",".join(sina_codes)

    try:
        req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
        with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as r:
            raw = r.read().decode("gbk")
    except:
        return {}

    results = {}
    for line in raw.strip().split("\n"):
        if not line or "=" not in line:
            continue
        var_name, values = line.split("=", 1)
        values = values.strip('"').strip('";')
        if not values:
            continue

        # 解析代码: hq_str_sh510300 → 510300
        code = var_name.replace("var hq_str_", "").replace("sh", "").replace("sz", "")
        code = code[-6:]  # take last 6 chars

        parts = values.split(",")
        if len(parts) < 10:
            continue

        name  = parts[0]
        open_p  = float(parts[1]) if parts[1] else 0
        prev_c  = float(parts[2]) if parts[2] else 0
        price   = float(parts[3]) if parts[3] else 0
        high    = float(parts[4]) if parts[4] else 0
        low     = float(parts[5]) if parts[5] else 0
        volume  = float(parts[8]) if len(parts) > 8 and parts[8] else 0  # 股
        amount  = float(parts[9]) if len(parts) > 9 and parts[9] else 0  # 元

        change_pct = (price - prev_c) / prev_c * 100 if prev_c > 0 else 0

        results[code] = {
            "name": name, "price": price, "open": open_p,
            "prev_close": prev_c, "high": high, "low": low,
            "volume_shares": volume, "amount": amount,
            "change_pct": round(change_pct, 3),
            "time": datetime.now().isoformat(),
        }
    return results


# ================================================================
# ② 盘后份额确认 (akshare — 盘后19:00后可用)
# ================================================================

def fetch_shares_confirmation():
    """盘后获取真实份额数据。
    返回: {code: {shares_yi, delta_yi, delta_pct}}
    盘中返回 None（份额数据未更新）
    """
    try:
        import akshare as ak
    except ImportError:
        return None

    now = datetime.now()
    # 盘后19:00前不查（份额还没更新）
    if now.hour < 19:
        return None

    today_str = now.strftime("%Y%m%d")
    shares = {}

    try:
        # 上交所份额
        df_sse = ak.fund_etf_scale_sse(date=today_str)
        if df_sse is not None and not df_sse.empty:
            for _, row in df_sse.iterrows():
                code = str(row.get("基金代码", ""))
                if code in ETFS:
                    shares_yi = float(row.get("基金份额", 0)) / 1e8  # 转为亿份
                    shares[code] = {"shares_yi": shares_yi, "source": "sse"}

        # 深交所份额
        df_szse = ak.fund_scale_daily_szse(start_date=today_str, end_date=today_str, symbol="ETF")
        if df_szse is not None and not df_szse.empty:
            for _, row in df_szse.iterrows():
                code = str(row.get("基金代码", ""))
                if code in ETFS:
                    shares_yi = float(row.get("基金份额", 0)) / 1e8
                    shares[code] = {"shares_yi": shares_yi, "source": "szse"}
    except:
        pass

    if not shares:
        return None

    # 与昨日对比计算delta
    hist_path = os.path.join(WORKSPACE, "etf_shares_history.json")
    if os.path.exists(hist_path):
        try:
            with open(hist_path, "r", encoding="utf-8") as f:
                hist = json.load(f)
            yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            for code in shares:
                if yesterday in hist and code in hist[yesterday]:
                    prev_shares = hist[yesterday][code].get("shares_yi", 0)
                    if prev_shares > 0:
                        delta = shares[code]["shares_yi"] - prev_shares
                        shares[code]["delta_yi"] = round(delta, 4)
                        shares[code]["delta_pct"] = round(delta / prev_shares * 100, 3)
        except:
            pass

    for code in shares:
        shares[code].setdefault("delta_yi", 0)
        shares[code].setdefault("delta_pct", 0)

    return shares


def _get_latest_share_delta(code, before_date=None):
    """获取最近可用的份额变化率(用于盘中没有当天份额数据时做代理)。
    优先从JSON历史读取, 其次从SQLite DB读取。
    before_date: 只使用该日期之前的数据(回测用), None=不限
    返回: delta_pct 或 None
    """
    # 优先从JSON历史文件读取
    hist_path = os.path.join(WORKSPACE, "etf_shares_history.json")
    if os.path.exists(hist_path):
        try:
            with open(hist_path, "r", encoding="utf-8") as f:
                hist = json.load(f)
            # 按日期降序排列, 找最新有该ETF份额变化的日期
            target_dates = sorted(hist.keys(), reverse=True)
            if before_date:
                target_dates = [d for d in target_dates if d < before_date]
            for date in target_dates:
                if isinstance(hist.get(date), dict) and code in hist[date]:
                    entry = hist[date][code]
                    delta = entry.get("delta_pct")
                    if delta is not None:
                        return delta
                    # 如果只有份额没有delta, 尝试计算
                    shares_yi = entry.get("shares_yi")
                    if shares_yi is not None:
                        prev = _find_prev_share(hist, code, date)
                        if prev is not None and prev > 0:
                            return round((shares_yi - prev) / prev * 100, 3)
        except:
            pass

    # 回退到SQLite DB
    try:
        import sqlite3
        db_path = os.path.join(WORKSPACE, "etf_history.db")
        if os.path.exists(db_path):
            with sqlite3.connect(db_path) as conn:
                if before_date:
                    row = conn.execute(
                        "SELECT shares_delta_pct FROM etf_daily "
                        "WHERE code=? AND shares_delta_pct IS NOT NULL AND date < ? "
                        "ORDER BY date DESC LIMIT 1", (code, before_date)
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT shares_delta_pct FROM etf_daily "
                        "WHERE code=? AND shares_delta_pct IS NOT NULL "
                        "ORDER BY date DESC LIMIT 1", (code,)
                    ).fetchone()
                if row:
                    return row[0]
    except:
        pass

    return None


def _find_prev_share(hist, code, date):
    """在历史份额数据中查找指定日期之前的最新份额值"""
    sorted_dates = sorted(hist.keys())
    idx = sorted_dates.index(date) if date in sorted_dates else -1
    if idx <= 0:
        return None
    for prev_d in sorted_dates[idx - 1::-1]:
        if isinstance(hist.get(prev_d), dict) and code in hist[prev_d]:
            return hist[prev_d][code].get("shares_yi")
    return None


# 相对强弱因子 — 已迁移至 etf_signals.calc_rs
# 保留别名以兼容直接引用
calc_relative_strength = calc_rs


# ================================================================
# ④ 连续日确认
# ================================================================

def check_consecutive_days(mid_count_today, high_count_today, resonance_min=3):
    """检查是否形成连续战役。
    返回: (consecutive_days, campaign_detected, confidence_boost)
    """
    hist_path = os.path.join(WORKSPACE, "signal_history.json")
    if not os.path.exists(hist_path):
        return 1, False, 0

    try:
        with open(hist_path, "r", encoding="utf-8") as f:
            history = json.load(f)
    except:
        return 1, False, 0

    today = datetime.now().strftime("%Y-%m-%d")
    consecutive = 1
    boost = 0

    # 按日期排序历史记录(最新在前), 跳过today自身
    sorted_history = sorted(history, key=lambda x: x.get("date", ""), reverse=True)
    sorted_history = [h for h in sorted_history if h.get("date") != today]

    for entry in sorted_history[:5]:
        if entry.get("mid_count", 0) >= resonance_min:
            consecutive += 1
        else:
            break

    campaign = consecutive >= 2
    if campaign:
        boost = min(30, consecutive * 10)  # 连续越久,加码越多

    return consecutive, campaign, boost


# ================================================================
# ⑤ ATR动态止损止盈
# ================================================================

def calc_atr(code, period=14):
    """计算ETF的ATR（平均真实波幅）"""
    data = _fetch_kline(code, period + 5)
    if len(data) < period:
        return None

    tr_values = []
    for i in range(1, min(len(data), period + 1)):
        high = data[-i]["h"]
        low  = data[-i]["l"]
        prev_c = data[-i-1]["c"]
        tr = max(high - low, abs(high - prev_c), abs(low - prev_c))
        tr_values.append(tr)

    if not tr_values:
        return None

    atr = sum(tr_values) / len(tr_values)
    return {
        "atr": round(atr, 4),
        "atr_pct": round(atr / data[-1]["c"] * 100, 2),  # ATR占价格百分比
        "stop_loss": round(data[-1]["c"] - atr * 2, 3),   # 2倍ATR止损
        "trail_stop": round(data[-1]["c"] - atr * 1.5, 3), # 1.5倍ATR跟踪
        "target_1": round(data[-1]["c"] + atr * 2, 3),     # 2倍ATR第一目标
        "target_2": round(data[-1]["c"] + atr * 3, 3),     # 3倍ATR第二目标
    }


def get_stop_loss_recommendation(code):
    """获取某只ETF的止损止盈建议文本"""
    atr_info = calc_atr(code)
    if not atr_info:
        return None

    return {
        "etf": code,
        "name": ETFS[code]["n"],
        "atr": atr_info["atr"],
        "atr_pct": atr_info["atr_pct"],
        "stop_loss": atr_info["stop_loss"],
        "stop_loss_pct": round(atr_info["atr_pct"] * 2, 2),
        "trailing_stop_pct": round(atr_info["atr_pct"] * 1.5, 2),
        "target_1_pct": round(atr_info["atr_pct"] * 2, 2),
        "target_2_pct": round(atr_info["atr_pct"] * 3, 2),
    }


# ================================================================
# ⑥ 宏观背景: 北向资金 + 连跌天数
# ================================================================

def fetch_north_flow():
    """获取北向资金净流向。
    返回: {net_flow_yi, consecutive_inflow_days, signal}
    盘中用东方财富API, 失败则返回None
    """
    try:
        # 东方财富北向资金实时API
        url = ("https://push2.eastmoney.com/api/qt/kamt.kline/get?"
               "fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54&klt=101&lmt=5")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10, context=ssl_ctx) as r:
            data = json.loads(r.read())

        if not data or not data.get("data") or not data["data"].get("klines"):
            return None

        klines = data["data"]["klines"]
        if not klines:
            return None

        latest = klines[-1].split(",")
        net_flow = float(latest[3]) if len(latest) > 3 else 0  # 北向净流入(万)

        # 判断连续流入天数
        consecutive = 0
        for k in reversed(klines):
            parts = k.split(",")
            flow = float(parts[3]) if len(parts) > 3 else 0
            if flow > 0:
                consecutive += 1
            else:
                break

        return {
            "net_flow_yi": round(net_flow / 10000, 2),  # 转为亿元
            "consecutive_inflow": consecutive,
            "signal": "inflow" if net_flow > 0 else "outflow",
            "strong": abs(net_flow) > 500000,  # 50亿以上视为显著
        }
    except:
        return None


def get_market_decline_days():
    """获取沪深300连续下跌天数"""
    idx_data = _fetch_kline("sh000300", 20)
    if len(idx_data) < 5:
        return 0

    decline_days = 0
    for i in range(len(idx_data) - 1, 0, -1):
        if idx_data[i]["c"] < idx_data[i-1]["c"]:
            decline_days += 1
        else:
            break
    return decline_days


def get_macro_context():
    """获取完整宏观背景。
    返回: {north_flow, decline_days, fear_level, context_score}
    """
    ctx = {
        "north_flow": fetch_north_flow(),
        "decline_days": get_market_decline_days(),
        "fear_level": "normal",
        "context_score": 0,
    }

    # 恐惧程度: 连跌越多越恐惧 → 国家队越可能出手
    if ctx["decline_days"] >= 5:
        ctx["fear_level"] = "extreme"
        ctx["context_score"] += 30
    elif ctx["decline_days"] >= 3:
        ctx["fear_level"] = "high"
        ctx["context_score"] += 20
    elif ctx["decline_days"] >= 1:
        ctx["fear_level"] = "moderate"
        ctx["context_score"] += 5

    # 北向剧烈流出 + 市场连跌 → 国家队维稳概率极高
    if ctx["north_flow"]:
        if ctx["north_flow"]["signal"] == "outflow" and ctx["north_flow"]["strong"]:
            ctx["context_score"] += 20  # 北向跑路时国家队常出手
        elif ctx["north_flow"]["signal"] == "inflow" and ctx["north_flow"]["consecutive_inflow"] >= 3:
            ctx["context_score"] += 15  # 北向+国家队共振,牛市确认

    return ctx


# ================================================================
# ⑦ 权重优化引擎
# ================================================================

def optimize_weights():
    """
    权重优化 — 已废弃 (2026-05-28).
    Walk-Forward验证: 60天滚动网格搜索在样本外不产生超额收益(平均-0.6%),
    且搜出的参数在窗口间不稳定。固定权重(50/20/30)在样本外表现更稳健。
    保留函数体用于手动验证, 但 get_optimal_weights() 直接返回固定值。
    """
    return {"vol": 0.50, "dir": 0.20, "share": 0.30}

# 保留旧实现(注释), 需要手动验证时取消注释:
# def optimize_weights():
#     ...原网格搜索实现...


# ================================================================
# 综合分析入口
# ================================================================

def full_analysis(codes=None, use_realtime=False, use_shares=False, weights=None):
    """
    完整三因子分析（整合所有改进）。

    参数:
      codes: ETF代码列表, None=全部
      use_realtime: True=新浪实时行情, False=日K线
      use_shares: True=获取真实份额, False=用默认值
      weights: 权重dict, None=默认50/20/30

    返回:
      {results: [...], resonance: {...}, macro: {...}, atr_stops: {...}}
    """
    if codes is None:
        codes = list(ETFS.keys())
    if weights is None:
        weights = {"vol": 0.50, "dir": 0.20, "share": 0.30}

    # ---- 宏观背景 ----
    macro = get_macro_context()

    # ---- 实时或日线行情 ----
    if use_realtime:
        rt = fetch_realtime(codes)
    else:
        rt = None

    # ---- 份额数据 ----
    if use_shares:
        shares = fetch_shares_confirmation()
    else:
        shares = None

    # ---- 逐只分析 ----
    idx_data = _fetch_kline("sh000300", 60)
    idx_chg = 0
    if len(idx_data) >= 2:
        idx_chg = (idx_data[-1]["c"] - idx_data[-2]["c"]) / idx_data[-2]["c"] * 100

    results = []
    for code in codes:
        info = ETFS[code]
        data = _fetch_kline(code, 60)
        if len(data) < 20:
            continue

        latest = data[-1]
        c, v = latest["c"], latest["v"]

        # 如果有实时数据，使用实时价格
        if rt and code in rt:
            c = rt[code]["price"]
            change_pct = rt[code]["change_pct"]
            # Sina返回股, 腾讯K线返回手 → 统一为手
            v = rt[code]["volume_shares"] / 100  # 股→手
        else:
            change_pct = 0
            if len(data) >= 2:
                change_pct = (c - data[-2]["c"]) / data[-2]["c"] * 100

        # 20日均量（不含当日）
        vols = [d["v"] for d in data[-21:-1]]
        vol_ma20 = sum(vols) / len(vols) if vols else 1
        vol_ratio = v / vol_ma20 if vol_ma20 > 0 else 1

        # === 量能因子 (原始值 0-1) ===
        vol_raw = min(1.0, max(0.0, (vol_ratio - 0.7) / 1.3)) if vol_ratio >= 0.7 else 0.0

        # === 相对强弱因子 (原始值 0-1) — 替代旧的方向因子 ===
        rs_score, is_counter = calc_rs(change_pct, idx_chg, vol_ratio)
        dir_raw = rs_score / 100.0

        # === 份额因子 (原始值 0-1) ===
        share_raw = 0.12  # 默认基准
        today_delta = None
        if shares and code in shares:
            today_delta = shares[code].get("delta_pct", 0)
        else:
            # 盘中份额未更新, 用最近历史份额变化作为代理(慢变量, 趋势延续)
            yesterday_delta = _get_latest_share_delta(code)
            if yesterday_delta is not None:
                today_delta = yesterday_delta * 0.7  # 历史数据打7折(时效折扣)

        if today_delta is not None:
            delta_pct = today_delta
            if delta_pct > 0.5:
                share_raw = min(1.0, 0.12 + delta_pct * 0.06)  # 正申购→加分
            elif delta_pct < -1:
                share_raw = max(0.0, 0.12 + delta_pct * 0.03)  # 大额赎回→减分
            share_raw = max(0.0, min(1.0, share_raw))

        # === 综合概率 ===
        cp = (vol_raw * weights["vol"] + dir_raw * weights["dir"] + share_raw * weights["share"]) * 100

        cp = max(0, min(100, cp))

        signal = "HIGH" if cp >= 70 else ("MID" if cp >= 50 else "LOW")

        results.append({
            "code": code, "name": info["n"], "idx_name": info["idx"],
            "date": latest["date"], "close": c,
            "change_pct": round(change_pct, 2),
            "vol_ratio": round(vol_ratio, 2),
            "vol_prob": round(vol_raw * 100, 1),
            "dir_prob": round(dir_raw * 100, 1),
            "share_prob": round(share_raw * 100, 1),
            "composite_prob": round(cp, 1),
            "signal": signal,
            "is_counter_market": is_counter,
            "idx_chg": round(idx_chg, 2),
        })

    # ---- 共振检测 ----
    mid_or_high = [r for r in results if r["composite_prob"] >= 50]
    high_only   = [r for r in results if r["composite_prob"] >= 70]

    # 连续日确认
    consecutive, campaign, conf_boost = check_consecutive_days(
        len(mid_or_high), len(high_only)
    )

    resonance = {
        "triggered": len(mid_or_high) >= 3,
        "high_count": len(high_only),
        "mid_count": len(mid_or_high),
        "consecutive_days": consecutive,
        "campaign_detected": campaign,
        "confidence_boost": conf_boost,
        "etfs": mid_or_high,
    }

    # ---- ATR止损建议 ----
    atr_stops = {}
    if mid_or_high:
        for r in mid_or_high[:5]:
            atr = get_stop_loss_recommendation(r["code"])
            if atr:
                atr_stops[r["code"]] = atr

    return {
        "results": results,
        "resonance": resonance,
        "macro": macro,
        "atr_stops": atr_stops,
        "weights_used": weights,
        "mode": "realtime" if use_realtime else "daily",
    }


# ================================================================
# 信号历史管理
# ================================================================

def save_signal_history(resonance_info):
    history_path = os.path.join(WORKSPACE, "signal_history.json")
    try:
        history = []
        if os.path.exists(history_path):
            with open(history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
    except:
        history = []

    today = datetime.now().strftime("%Y-%m-%d")
    history = [h for h in history if h.get("date") != today]
    history.append({
        "date": today,
        "time": datetime.now().isoformat(),
        "mid_count": resonance_info["mid_count"],
        "high_count": resonance_info["high_count"],
        "consecutive": resonance_info.get("consecutive_days", 1),
    })
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history[-30:], f, ensure_ascii=False, indent=2)


def get_optimal_weights():
    """获取因子权重 — 固定50/20/30。
    Walk-Forward验证后废弃了60天滚动网格搜索优化,
    固定权重在样本外表现更稳健(平均+0.6%超额 vs 搜索版)。
    """
    return {"vol": 0.50, "dir": 0.20, "share": 0.30}


# ================================================================
# v4 新增: 趋势检测 + 动态阈值 + ATR跟踪退出
# ================================================================

def detect_market_trend(code="510300", ma_period=50):
    """检测市场趋势 — 委托至 etf_signals.detect_trend。
    返回: {trend: 'up'|'down'|'neutral', slope: 均线斜率(%), strength: 0-100, above_ma: bool}
    """
    data = _fetch_kline(code, ma_period + 10)
    if len(data) < ma_period:
        return {"trend": "neutral", "slope": 0, "strength": 50, "above_ma": True}
    return detect_trend(data, len(data) - 1, ma_period)


def get_dynamic_params(trend_info):
    """动态参数 — 简化版(2状态), Walk-Forward验证后精简。
    上升: ≥2只≥50%, 持7天, 可叠仓
    非上升: ≥3只≥50%, 持5天, 不叠仓

    原4状态版本(4212网格搜索最优)在Walk-Forward中参数不稳定,
    样本外表现不如固定简化版, 已废弃。
    """
    t = trend_info["trend"]

    if t == "up":
        return {"cp_threshold": 50, "resonance_min": 2, "hold_days": 7,
                "allow_pyramiding": True, "label": "上升"}
    else:
        return {"cp_threshold": 50, "resonance_min": 3, "hold_days": 5,
                "allow_pyramiding": False, "label": "非上升(防御)"}


def get_min_position(trend_info):
    """根据趋势返回建议底仓比例 — 简化版。
    仅上升趋势+强度≥60时建底仓, 非上升不做底仓。
    Walk-Forward验证: 复杂版底仓(4级强度)在样本外无超额收益。
    返回: (min_pct, reason)
    """
    if trend_info["trend"] == "up" and trend_info.get("strength", 50) >= 60:
        return 0.25, f"上升趋势(强度{trend_info['strength']:.0f})"
    return 0.0, "非上升趋势,不做底仓"


def calc_dynamic_exit(entry_price, highest_since_entry, atr, days_held,
                       time_stop=8, target_pct=5.0, trail_mult=1.5):
    """动态退出判断。

    参数:
      entry_price: 买入价
      highest_since_entry: 持仓期间最高收盘价
      atr: 当前ATR值
      days_held: 已持有天数
      time_stop: 时间止损(天)
      target_pct: 目标止盈(%)
      trail_mult: 跟踪止损ATR倍数

    返回: (should_exit: bool, reason: str, exit_price: float|None)
    """
    # ① 时间止损
    if days_held >= time_stop:
        return True, f"时间止损(持{days_held}天)", None

    # ② 目标止盈
    profit_pct = (highest_since_entry - entry_price) / entry_price * 100
    if profit_pct >= target_pct:
        return True, f"目标止盈(+{profit_pct:.1f}%)", None

    # ③ ATR跟踪止损
    trail_stop = highest_since_entry - atr * trail_mult
    current_trigger = trail_stop  # 如果收盘价跌破此价就卖

    # 追踪止损只在盈利后才激活（买入价作为初始止损）
    if profit_pct > 0:
        return False, "", trail_stop
    else:
        # 亏损中: 用固定2倍ATR止损
        hard_stop = entry_price - atr * 2
        return False, "", hard_stop


# ================================================================
# v4 新增: 核心-卫星组合模拟
# ================================================================

def core_satellite_equity(strategy_equity, bh_equity, core_pct=0.70):
    """核心-卫星组合权益曲线。
    core_pct: 买持比例 (默认70%)
    satellite_pct: 策略比例 (默认30%)
    """
    if not strategy_equity or not bh_equity:
        return None

    min_len = min(len(strategy_equity), len(bh_equity))
    sat_pct = 1.0 - core_pct

    combined = []
    for i in range(min_len):
        strategy_val = strategy_equity[i] / strategy_equity[0] * INITIAL_CAPITAL
        bh_val = bh_equity[i] / bh_equity[0] * INITIAL_CAPITAL
        combined.append(strategy_val * sat_pct + bh_val * core_pct)

    return combined

INITIAL_CAPITAL = 100000  # used by core_satellite_equity


# ================================================================
# 测试
# ================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("ETF引擎 v4 功能测试")
    print("=" * 60)

    print("\n① 实时行情测试:")
    rt = fetch_realtime()
    for code, d in list(rt.items())[:3]:
        print(f"  {code}: {d['price']:.3f} | {d['change_pct']:+.3f}% | 量{d['volume_shares']:.0f}股")

    print("\n② 份额数据测试:")
    shares = fetch_shares_confirmation()
    if shares:
        for code, d in list(shares.items())[:3]:
            print(f"  {code}: {d['shares_yi']:.1f}亿 | Δ{d['delta_pct']:+.2f}%")
    else:
        print("  (盘前/盘中, 份额数据尚不可用)")

    print("\n③ 相对强弱测试:")
    print(f"  大盘跌1%+ETF涨0.5% → {calc_relative_strength(0.5, -1.0, 1.5)}")
    print(f"  大盘涨2%+ETF涨2.5% → {calc_relative_strength(2.5, 2.0, 0.9)}")
    print(f"  大盘跌2%+ETF微跌0.2%+放量1.5x → {calc_relative_strength(-0.2, -2.0, 1.5)}")

    print("\n④ 连续日确认:")
    cons, camp, boost = check_consecutive_days(4, 2)
    print(f"  4中+2高 → 连续{cons}日, 战役={'是' if camp else '否'}, 加码{boost}")

    print("\n⑤ ATR止损测试:")
    atr = calc_atr("510300")
    if atr:
        print(f"  510300 ATR={atr['atr']:.4f} ({atr['atr_pct']}%) | "
              f"止损{atr['stop_loss']:.3f} | 目标{atr['target_1']:.3f}")

    print("\n⑥ 宏观背景:")
    macro = get_macro_context()
    print(f"  连跌: {macro['decline_days']}日 | 恐惧: {macro['fear_level']} | 评分: {macro['context_score']}")
    if macro["north_flow"]:
        print(f"  北向: {macro['north_flow']['net_flow_yi']:.1f}亿 | {macro['north_flow']['signal']}")

    print("\n⑦ 权重优化:")
    weights = get_optimal_weights()
    print(f"  最优: v={weights['vol']:.0%} d={weights['dir']:.0%} s={weights['share']:.0%}")

    print("\n⑧ v4 趋势检测:")
    trend = detect_market_trend()
    print(f"  趋势: {trend['trend']} | 斜率: {trend['slope']}% | 强度: {trend['strength']}")
    params = get_dynamic_params(trend)
    print(f"  动态参数: {params}")

    print("\n⑨ v4 动态退出:")
    exit_info = calc_dynamic_exit(4.5, 4.7, 0.075, days_held=5, time_stop=8, target_pct=5.0)
    print(f"  买4.5, 最高4.7, 持5天, ATR=0.075 → {exit_info}")

    print("\n--- v4全部测试完成 ---")
