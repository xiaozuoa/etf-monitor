#!/usr/bin/env python3
"""
ETF国家队实时监控 v2 — 共振确认策略
改进: ①阈值60% ②≥3只ETF共振 ③连日趋确认 ④份额盘后加码
≥60%综合概率 + 多ETF共振时立即发送买入建议邮件
"""

import os, sys, io, smtplib, json, time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

# UTF-8 fix (harmless on Linux, critical on Windows)
if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
from etf_v7_threefactor import fetch
from etf_v7_threefactor import ETFS as _ETFS_ORIG

# ---- 配置（优先环境变量，fallback配置文件） ----
WORKSPACE = os.path.expanduser("~/.etf-skill/workspace")
CONFIG_FILE = os.path.join(WORKSPACE, "alert_config.json")
SENT_LOG    = os.path.join(WORKSPACE, "alert_sent.json")
SIGNAL_LOG  = os.path.join(WORKSPACE, "signal_history.json")
os.makedirs(WORKSPACE, exist_ok=True)

def _load_config():
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        except:
            pass
    return {
        "email_from": os.environ.get("ETF_EMAIL_FROM") or cfg.get("email_from", ""),
        "email_to":   os.environ.get("ETF_EMAIL_TO")   or cfg.get("email_to", ""),
        "smtp_pass":  os.environ.get("SMTP_PASS") or os.environ.get("QQMAIL_AUTH_CODE") or cfg.get("smtp_pass", ""),
        "smtp_host":  os.environ.get("ETF_SMTP_HOST")  or cfg.get("smtp_host", "smtp.qq.com"),
        "smtp_port":  int(os.environ.get("ETF_SMTP_PORT") or cfg.get("smtp_port", "465")),
    }

CFG = _load_config()
ETFS = _ETFS_ORIG

# ---- 改进策略参数 ----
CP_THRESHOLD     = 60.0   # 单只ETF阈值（原70%，从未触发）
RESONANCE_MIN    = 3      # 至少N只ETF同时≥50%才算真进场
LOOKBACK_DAYS    = 2      # 连日趋回溯天数
MIN_GAP_HOURS    = 3      # 同一信号最少间隔


def get_idx_chg():
    data = fetch("sh000300", 5)
    if len(data) >= 2:
        return (data[-1]["c"] - data[-2]["c"]) / data[-2]["c"] * 100
    return 0


def analyze_etf(code, info):
    """单只ETF三因子分析"""
    data = fetch(code, 60)
    if len(data) < 20:
        return None

    latest = data[-1]
    c, v = latest["c"], latest["v"]
    date = latest["date"]

    change_pct = 0
    if len(data) >= 2:
        change_pct = (c - data[-2]["c"]) / data[-2]["c"] * 100

    vols = [d["v"] for d in data[-20:]]
    vol_ma20 = sum(vols) / 20
    vol_ratio = v / vol_ma20 if vol_ma20 > 0 else 1

    # 量能概率
    vol_prob = min(100, max(0, (vol_ratio - 0.7) / 1.3 * 100)) if vol_ratio >= 0.7 else 0

    # 方向概率
    idx_chg = get_idx_chg()
    dir_prob = 0
    if len(data) >= 2:
        if idx_chg < 0 and change_pct > 0:
            dir_prob += 30
        elif idx_chg < -0.5 and change_pct > idx_chg + 0.3:
            dir_prob += 30
        excess = change_pct - idx_chg
        if excess > 0.5:
            dir_prob += min(25, excess * 8)
        if len(data) >= 4:
            prev3_chg = (c - data[-4]["c"]) / data[-4]["c"] * 100
            if prev3_chg < -1:
                dir_prob += min(20, abs(prev3_chg) * 3)
        if vol_ratio > 1.2 and change_pct > 0:
            dir_prob += 15
        dir_prob = min(100, dir_prob)

    share_prob = 12
    composite = vol_prob * 0.50 + dir_prob * 0.20 + share_prob * 0.30

    return {
        "code": code, "name": info["n"], "idx_name": info["idx"],
        "date": date, "close": c, "change_pct": round(change_pct, 2),
        "vol_ratio": round(vol_ratio, 2),
        "vol_prob": round(vol_prob, 1), "dir_prob": round(dir_prob, 1),
        "share_prob": share_prob,
        "composite_prob": round(composite, 1),
        "signal": "HIGH" if composite >= 60 else ("MID" if composite >= 50 else "LOW"),
        "idx_chg": round(idx_chg, 2),
    }


def load_json(path, default=None):
    if default is None:
        default = {}
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return default
    return default


def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def check_resonance(results):
    """检查是否存在多ETF共振"""
    mid_or_high = [r for r in results if r["composite_prob"] >= 50]
    high_only   = [r for r in results if r["composite_prob"] >= CP_THRESHOLD]

    if len(mid_or_high) < RESONANCE_MIN:
        return None  # 不到3只共振，不触发

    # 信号强度 = 高确信数量 + 中等数量
    strength = len(high_only) * 2 + (len(mid_or_high) - len(high_only))
    max_cp    = max(r["composite_prob"] for r in mid_or_high)

    # 检查连续趋势
    signal_hist = load_json(SIGNAL_LOG, [])
    today = datetime.now().strftime("%Y-%m-%d")
    consecutive = 1
    for entry in reversed(signal_hist):
        entry_date = entry.get("date", "")
        if entry_date == today:
            continue
        # 前1-2个交易日是否有信号
        d = datetime.strptime(today, "%Y-%m-%d")
        prev_dates = [(d - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, LOOKBACK_DAYS+1)]
        if entry_date in prev_dates and entry.get("mid_count", 0) >= RESONANCE_MIN:
            consecutive = entry.get("consecutive", 1) + 1
            break

    return {
        "high_count": len(high_only),
        "mid_count": len(mid_or_high),
        "resonance": len(mid_or_high) >= RESONANCE_MIN,
        "strength": strength,
        "max_cp": max_cp,
        "consecutive": consecutive,
        "etfs": mid_or_high,
    }


def save_signal_history(resonance_info):
    """保存今日信号到历史记录"""
    history = load_json(SIGNAL_LOG, [])
    today = datetime.now().strftime("%Y-%m-%d")

    # 只保留最近一条同一天记录，更新它
    history = [h for h in history if h.get("date") != today]
    history.append({
        "date": today,
        "time": datetime.now().isoformat(),
        "mid_count": resonance_info["mid_count"],
        "high_count": resonance_info["high_count"],
        "strength": resonance_info["strength"],
        "consecutive": resonance_info["consecutive"],
    })

    # 只保留最近30条
    save_json(SIGNAL_LOG, history[-30:])


def should_send():
    """判断是否应该发送邮件（防重复）"""
    log = load_json(SENT_LOG, {})
    last_key = log.get("last_sent", "")
    if not last_key:
        return True

    parts = last_key.split("_")
    if len(parts) >= 2:
        last_time = datetime.fromisoformat(parts[1])
        if (datetime.now() - last_time).total_seconds() > MIN_GAP_HOURS * 3600:
            return True
    return False


def mark_sent():
    log = load_json(SENT_LOG, {})
    log["last_sent"] = f"{datetime.now().strftime('%Y%m%d')}_{datetime.now().isoformat()}"
    save_json(SENT_LOG, log)


def send_alert_email(resonance):
    """发送增强版买入建议"""
    if not CFG["smtp_pass"]:
        print("  未配置SMTP密码，跳过邮件")
        return False

    now = datetime.now()
    alerts = resonance["etfs"]
    consecutive_bonus = " + 连日趋确认" if resonance["consecutive"] >= 2 else ""
    level = "🔥🔥🔥 极度确信" if resonance["consecutive"] >= 2 else ("🔥🔥 高度确信" if resonance["high_count"] >= 2 else "🔥 确信")

    subject = f"{level} 国家队多ETF共振进场 — {now.strftime('%m-%d %H:%M')}"

    lines = []
    lines.append(f"检测时间: {now.strftime('%Y-%m-%d %H:%M')} (北京时间)")
    lines.append(f"信号等级: {level}{consecutive_bonus}")
    lines.append(f"共振ETF: {resonance['mid_count']}只 (高确信{resonance['high_count']}只)")
    lines.append(f"最高概率: {resonance['max_cp']:.1f}%")
    lines.append("")

    lines.append("=" * 50)
    lines.append("【国家队进场ETF明细】")
    lines.append("=" * 50)

    for a in sorted(alerts, key=lambda x: x["composite_prob"], reverse=True):
        icon = "🔴" if a["composite_prob"] >= 60 else "🟡"
        lines.append("")
        lines.append(f"  {icon} {a['code']} {a['name']}")
        lines.append(f"  指数: {a['idx_name']} | 现价: {a['close']:.3f}元")
        lines.append(f"  涨幅: {a['change_pct']:+.2f}% | 沪深300: {a['idx_chg']:+.2f}%")
        lines.append(f"  综合概率: {a['composite_prob']:.1f}% (量{a['vol_prob']:.0f} 向{a['dir_prob']:.0f} 份{a['share_prob']:.0f})")
        lines.append(f"  量比: {a['vol_ratio']:.2f}x")

    lines.append("")
    lines.append("=" * 50)
    lines.append("【买入策略 — 共振确认版】")
    lines.append("=" * 50)
    lines.append("")

    if resonance["consecutive"] >= 2:
        lines.append("  ⚡ 连续{0}日共振 → 国家队战役级操作，优先重仓".format(resonance["consecutive"]))
        lines.append("  仓位: 60%首仓 + 40%回调加仓")
    elif resonance["high_count"] >= 2:
        lines.append("  ⚡ 多只高确信 → 国家队明确进场")
        lines.append("  仓位: 50%首仓 + 50%回调加仓")
    else:
        lines.append("  ⚡ {0}只ETF共振 → 初步进场信号".format(resonance["mid_count"]))
        lines.append("  仓位: 30%试探仓 + 确认后加仓")

    lines.append("")
    lines.append("  买入时机:")
    lines.append("    ① 次日开盘买入首仓")
    lines.append("    ② 若开盘涨幅>1%: 等回调至昨日收盘价附近再买")
    lines.append("    ③ 若开盘下跌<1%: 直接买入（市场还没反应）")
    lines.append("")

    # 选均价做参考
    avg_price = sum(a["close"] for a in alerts) / len(alerts)
    lines.append(f"  价格参考: ETF均价约 {avg_price:.3f}元")
    lines.append(f"  止损: 买入成本-3%")
    lines.append(f"  止盈: 分批，+3%卖1/3，+5%卖1/3，+8%清仓")
    lines.append("")
    lines.append("---")
    lines.append("ETF三因子v2共振监控 · 自动发送 · 仅供参考")

    body = "\n".join(lines)

    msg = MIMEMultipart()
    msg["From"] = CFG["email_from"]
    msg["To"] = CFG["email_to"]
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        server = smtplib.SMTP_SSL(CFG["smtp_host"], CFG["smtp_port"], timeout=30)
        server.login(CFG["email_from"], CFG["smtp_pass"])
        server.sendmail(CFG["email_from"], CFG["email_to"], msg.as_string())
        server.quit()
        print(f"  ✅ 买入建议邮件已发送至 {CFG['email_to']}")
        return True
    except Exception as e:
        print(f"  ❌ 邮件发送失败: {e}")
        return False


def main():
    print("=" * 60)
    print(f"🔍 ETF国家队共振监控 v2  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   策略: 单只≥{CP_THRESHOLD}% + ≥{RESONANCE_MIN}只共振 + 连日趋确认")
    print("=" * 60)

    # 逐只分析
    results = []
    for code, info in ETFS.items():
        r = analyze_etf(code, info)
        if r:
            results.append(r)

    if not results:
        print("  数据获取失败")
        return

    # 共振检测
    resonance = check_resonance(results)

    # 打印状态
    high_n = sum(1 for r in results if r["composite_prob"] >= CP_THRESHOLD)
    mid_n  = sum(1 for r in results if CP_THRESHOLD > r["composite_prob"] >= 50)
    print(f"  高确信(≥{CP_THRESHOLD}%): {high_n}只 | 中等(50-{CP_THRESHOLD-1}%): {mid_n}只")
    print(f"  共振条件: ≥{RESONANCE_MIN}只同时≥50% → ", end="")

    if resonance and resonance["resonance"]:
        print(f"✅ 触发! ({resonance['mid_count']}只共振, 强度{resonance['strength']})\n")
        for r in sorted(results, key=lambda x: x["composite_prob"], reverse=True):
            icon = "🔴" if r["composite_prob"] >= 60 else ("🟡" if r["composite_prob"] >= 50 else "⚪")
            print(f"  {icon} {r['code']} {r['name']}: CP={r['composite_prob']}% (V{r['vol_prob']:.0f} D{r['dir_prob']:.0f})")

        if should_send():
            print(f"\n🚨 共振信号确认，发送买入建议...")
            if resonance["consecutive"] >= 2:
                print(f"  ⚡ 已连续{resonance['consecutive']}日 → 国家队战役级操作!")
            save_signal_history(resonance)
            send_alert_email(resonance)
            mark_sent()
        else:
            print(f"\n  {MIN_GAP_HOURS}小时内已发送过，跳过")
    else:
        print(f"❌ 未触发 (共{sum(1 for r in results if r['composite_prob']>=50)}只≥50%)")
        # 即使不触发也记录（用于连日趋检测）
        mid_count = sum(1 for r in results if r["composite_prob"] >= 50)
        if mid_count >= 1:
            save_signal_history({
                "mid_count": mid_count, "high_count": high_n,
                "strength": high_n * 2 + (mid_count - high_n),
                "consecutive": 1,
            })

    for r in sorted(results, key=lambda x: x["composite_prob"], reverse=True):
        icon = "🔴" if r["composite_prob"] >= 60 else ("🟡" if r["composite_prob"] >= 50 else "⚪")
        print(f"  {icon} {r['code']} {r['name']}: CP={r['composite_prob']}%")

    print("--- done ---")


if __name__ == "__main__":
    main()
