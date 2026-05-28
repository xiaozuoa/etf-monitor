#!/usr/bin/env python3
"""ETF信号共享模块 — 统一的数据获取、趋势检测、CP计算，避免多文件复制漂移"""

import json, urllib.request, ssl

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

COMMISSION = 0.00025
SLIPPAGE = 0.0005
INITIAL = 100000

# CP权重 — P0统一版 (50/20/30)
W_VOL = 0.50
W_DIR = 0.20
W_SHARE = 0.30
DEFAULT_SHARE_RAW = 0.12


def fetch(code, limit=800):
    """腾讯K线数据，返回 [{date, o, c, h, l, v}, ...]"""
    if code.startswith("sh") or code.startswith("sz"):
        pfx2, nc = code[:2], code[2:]
    else:
        pfx2 = "sh" if code.startswith(("51", "56", "0")) else "sz"
        nc = code
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={pfx2}{nc},day,,,{limit},qfq"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as r:
        d = json.loads(r.read().decode("utf-8"))
    k = d.get("data", {}).get(f"{pfx2}{nc}", {}).get("qfqday", []) or \
        d.get("data", {}).get(f"{pfx2}{nc}", {}).get("day", [])
    return [{"date": r[0], "o": float(r[1]), "c": float(r[2]),
             "h": float(r[3]), "l": float(r[4]), "v": float(r[5])}
            for r in k if len(r) >= 6 and r[0]]


def detect_trend(ref, day_i, ma_period=50):
    """检测市场趋势 — 正确版MA斜率计算。
    MA斜率 = (当前MA50 - 10天前MA50) / 10天前MA50
    需要 ma_period+10 个数据点 (60天窗口)。
    """
    need = ma_period + 10
    if day_i < need:
        return {"trend": "neutral", "slope": 0, "strength": 50, "above_ma": True}

    closes_all = [d["c"] for d in ref[day_i - need + 1:day_i + 1]]
    ma_now = sum(closes_all[-ma_period:]) / ma_period
    ma_10d_ago = sum(closes_all[:ma_period]) / ma_period  # MA50 ending 10 days ago
    slope = (ma_now - ma_10d_ago) / ma_10d_ago * 100 if ma_10d_ago > 0 else 0
    above = ref[day_i]["c"] > ma_now

    if slope > 1.0 and above:
        t = "up"
    elif slope < -1.0 and not above:
        t = "down"
    else:
        t = "neutral"
    s = max(0, min(100, 50 + abs(slope) * 15)) if t != "neutral" else 50
    return {"trend": t, "slope": round(slope, 2), "strength": round(s, 1), "above_ma": above}


def calc_rs(etf_chg, idx_chg, vol_ratio):
    """相对强弱得分 0-100"""
    excess = etf_chg - idx_chg
    score, is_c = 0, False
    if idx_chg < -0.5 and etf_chg > idx_chg + 0.3:
        score += 40
        is_c = True
    if idx_chg < -1.5 and is_c:
        score += min(20, abs(idx_chg) * 3)
    if idx_chg < -0.5 and vol_ratio > 1.3 and etf_chg > idx_chg + 0.5:
        score += 25
    if excess > 0.3:
        score += min(20, excess * 6)
    if idx_chg > 1.5 and 0 < excess < 0.3:
        score -= 15
    if idx_chg > 2.0 and excess < 0.5:
        score -= 10
    if etf_chg > 1.5 and vol_ratio < 0.8:
        score -= 20
    return max(0, min(100, score)), is_c


def compute_cp(records, day_i, idx_chg, share_raw=None):
    """综合概率 (P0统一版: 量能50% + 方向20% + 份额30%)

    share_raw: 份额因子原始值 0-1. None=使用默认值0.12.
      生产环境盘中份额数据通常不可用(盘后19:00才更新), 用历史代理打7折;
      回测环境若无真实历史份额数据, share_raw恒为0.12, 份额因子贡献恒定3.6分.
      这意味着回测的份额因子不提供选时能力, 实际生产中的份额动态贡献(0-30分)未在回测中验证.
      要弥合这个差距需回填真实历史份额数据(akshare SSE/SZSE)到回测中.
    """
    if share_raw is None:
        share_raw = DEFAULT_SHARE_RAW
    r = records[day_i]
    c, v = r["c"], r["v"]
    chg = (c - records[day_i - 1]["c"]) / records[day_i - 1]["c"] * 100
    vols = [records[j]["v"] for j in range(max(0, day_i - 20), day_i)]
    ma20 = sum(vols) / len(vols) if vols else 1
    vr = v / ma20 if ma20 > 0 else 1
    v_raw = min(1, max(0, (vr - 0.7) / 1.3)) if vr >= 0.7 else 0
    rs, is_c = calc_rs(chg, idx_chg, vr)
    d_raw = rs / 100
    return (v_raw * W_VOL + d_raw * W_DIR + share_raw * W_SHARE) * 100, chg, vr, is_c, c
