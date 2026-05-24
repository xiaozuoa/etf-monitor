#!/usr/bin/env python3
"""
ETF国家队共振监控 v3 — 两阶段确认 (盘中初筛 + 盘后确认)
只有盘后拿到真实份额数据 + 连续日确认后才发买入邮件
"""

import os, sys, io, smtplib, json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

if hasattr(sys.stdout, 'buffer') and sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from etf_engine import (full_analysis, get_optimal_weights, save_signal_history,
                         ETFS, WORKSPACE)

# ---- 配置 ----
CONFIG_FILE = os.path.join(WORKSPACE, "alert_config.json")
SENT_LOG    = os.path.join(WORKSPACE, "alert_sent_v3.json")
os.makedirs(WORKSPACE, exist_ok=True)


def load_config():
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


CFG = load_config()
MIN_GAP_HOURS = 2


def should_send():
    log = {}
    if os.path.exists(SENT_LOG):
        try:
            with open(SENT_LOG, 'r', encoding='utf-8') as f:
                log = json.load(f)
        except:
            pass
    last_key = log.get("last_sent", "")
    if not last_key:
        return True
    parts = last_key.split("_")
    if len(parts) >= 2:
        last_time = datetime.fromisoformat(parts[1])
        return (datetime.now() - last_time).total_seconds() > MIN_GAP_HOURS * 3600
    return True


def mark_sent():
    log = {}
    if os.path.exists(SENT_LOG):
        try:
            with open(SENT_LOG, 'r', encoding='utf-8') as f:
                log = json.load(f)
        except:
            pass
    log["last_sent"] = f"{datetime.now().strftime('%Y%m%d')}_{datetime.now().isoformat()}"
    with open(SENT_LOG, 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def send_buy_email(analysis, is_post_market=False):
    """发送买入建议邮件"""
    if not CFG["smtp_pass"]:
        print("  未配置SMTP，跳过")
        return False

    res  = analysis["resonance"]
    macro = analysis["macro"]
    atrs  = analysis["atr_stops"]
    alerts = res["etfs"]

    now = datetime.now()

    # 分级标题
    if res["campaign_detected"]:
        if res["consecutive_days"] >= 3:
            level = "🔥🔥🔥 战役级连续{0}日".format(res["consecutive_days"])
        else:
            level = "🔥🔥 连续{0}日共振".format(res["consecutive_days"])
    elif res["high_count"] >= 3:
        level = "🔥🔥 多只高确信共振"
    elif is_post_market:
        level = "🔥 盘后份额确认"
    else:
        level = "📡 盘中初筛"

    subject = f"{level} 国家队ETF进场 — {now.strftime('%m-%d %H:%M')}"

    lines = []
    lines.append(f"检测时间: {now.strftime('%Y-%m-%d %H:%M')} (北京时间)")
    lines.append(f"模式: {'盘后双重确认' if is_post_market else '盘中实时初筛'}")
    lines.append(f"信号: {res['mid_count']}只共振 (高确信{res['high_count']}只)")
    if res["consecutive_days"] >= 2:
        lines.append(f"⚡ 已连续{res['consecutive_days']}个交易日 → 国家队战役级操作")
    lines.append("")

    # 宏观背景
    if macro["decline_days"] >= 3:
        lines.append(f"⚠️ 市场已连跌{macro['decline_days']}日,恐惧程度:{macro['fear_level']}")
        lines.append("   国家队此时出手是典型的维稳操作")
    if macro["north_flow"]:
        nf = macro["north_flow"]
        lines.append(f"北向资金: {nf['net_flow_yi']:+.1f}亿 ({nf['signal']})")

    lines.append("")
    lines.append("=" * 50)
    lines.append("【进场ETF明细】")
    lines.append("=" * 50)

    for a in sorted(alerts, key=lambda x: x["composite_prob"], reverse=True):
        icon = "🔴" if a["composite_prob"] >= 60 else "🟡"
        counter = " ⚡逆市抗跌" if a.get("is_counter_market") else ""
        lines.append("")
        lines.append(f"  {icon} {a['code']} {a['name']}{counter}")
        lines.append(f"  跟踪: {a['idx_name']} | 现价: {a['close']:.3f}元 | {a['change_pct']:+.2f}%")
        lines.append(f"  综合概率: {a['composite_prob']:.1f}% "
                     f"(量{a['vol_prob']:.0f} 向{a['dir_prob']:.0f} 份{a['share_prob']:.0f})")
        lines.append(f"  量比: {a['vol_ratio']:.2f}x")

        # ATR止损
        if a['code'] in atrs:
            atr = atrs[a['code']]
            lines.append(f"  ATR止蚀: {atr['stop_loss_pct']}% | 目标: +{atr['target_1_pct']}% / +{atr['target_2_pct']}%")

    lines.append("")
    lines.append("=" * 50)
    lines.append("【买入策略 — v3动态版】")
    lines.append("=" * 50)
    lines.append("")

    # 仓位建议
    if is_post_market and res["campaign_detected"]:
        if res["consecutive_days"] >= 3:
            lines.append("  ⚡ 连续3日战役 → 重仓出击")
            lines.append("  仓位: 70%首仓 + 30%备援")
        else:
            lines.append("  ⚡ 连续{0}日 + 盘后份额确认 → 标准仓位".format(res["consecutive_days"]))
            lines.append("  仓位: 50%首仓 + 50%回调加仓")
    elif is_post_market and res["high_count"] >= 2:
        lines.append("  ⚡ 盘后确认 + 多只高确信 → 中等仓位")
        lines.append("  仓位: 40%首仓 + 分批加仓")
    else:
        lines.append("  📡 盘中初筛 → 先关注不等买入")
        lines.append("  仓位: 等待盘后确认邮件再决定")

    if is_post_market:
        lines.append("")
        lines.append("  买入执行:")
        lines.append("    ① 次日开盘: 买入首仓")
        lines.append("    ② 若开盘涨>1%: 等回调至昨日收盘价±0.3%再买")
        lines.append("    ③ 若开盘跌: 直接买入(有利价格)")
        lines.append("    ④ 盘中止损: 按各ETF的ATR动态止损(见上表)")
        lines.append("    ⑤ 跟踪止盈: 持仓期间最高价回落1.5倍ATR时止盈")
        lines.append("    ⑥ 持有周期: 3-5个交易日(国家队战役通常持续周期)")

    lines.append("")
    lines.append("---")
    lines.append("ETF三因子v3共振监控 · GitHub Actions云端 · 仅供参考")

    body = "\n".join(lines)

    msg = MIMEMultipart()
    msg["From"] = CFG["email_from"]
    msg["To"] = CFG["email_to"]
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        import smtplib
        server = smtplib.SMTP_SSL(CFG["smtp_host"], CFG["smtp_port"], timeout=30)
        server.login(CFG["email_from"], CFG["smtp_pass"])
        server.sendmail(CFG["email_from"], CFG["email_to"], msg.as_string())
        server.quit()
        print(f"  ✅ 买入建议已发送 → {CFG['email_to']}")
        return True
    except Exception as e:
        print(f"  ❌ 发送失败: {e}")
        return False


def run(is_post_market=None):
    """主监控入口。
    is_post_market: None=自动判断, True=盘后模式, False=盘中模式
    """
    if is_post_market is None:
        now = datetime.now()
        is_post_market = now.hour >= 19

    use_shares = is_post_market
    use_realtime = not is_post_market

    print("=" * 60)
    print(f"🔍 ETF国家队共振监控 v3  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   模式: {'盘后双重确认' if is_post_market else '盘中实时初筛'}")
    print(f"   数据: {'真实份额' if use_shares else '默认份额'} + "
          f"{'实时行情' if use_realtime else '日K线'}")
    print("=" * 60)

    # 获取最优权重
    weights = get_optimal_weights()
    print(f"   权重: 量{weights['vol']*100:.0f}% 向{weights['dir']*100:.0f}% 份{weights['share']*100:.0f}%")

    # 完整分析
    analysis = full_analysis(
        use_realtime=use_realtime,
        use_shares=use_shares,
        weights=weights,
    )

    results   = analysis["results"]
    resonance = analysis["resonance"]

    # 打印状态
    high_n = sum(1 for r in results if r["composite_prob"] >= 60)
    mid_n  = sum(1 for r in results if 60 > r["composite_prob"] >= 50)
    print(f"  高确信(≥60%): {high_n} | 中等(50-59%): {mid_n} | 共振(≥3只≥50%): {'✅' if resonance['triggered'] else '❌'}")

    for r in sorted(results, key=lambda x: x["composite_prob"], reverse=True):
        icon = "🔴" if r["composite_prob"] >= 60 else ("🟡" if r["composite_prob"] >= 50 else "⚪")
        counter = " ⚡抗跌" if r.get("is_counter_market") else ""
        print(f"  {icon} {r['code']} {r['name']}: CP={r['composite_prob']}%"
              f" (V{r['vol_prob']:.0f} D{r['dir_prob']:.0f} S{r['share_prob']:.0f}){counter}")

    # 宏观
    macro = analysis["macro"]
    if macro["decline_days"] >= 3:
        print(f"  ⚠️ 市场连跌{macro['decline_days']}日 | 恐惧:{macro['fear_level']}")

    # 决策逻辑
    if not resonance["triggered"]:
        print(f"\n  未触发 (仅{resonance['mid_count']}只≥50%, 需≥3只)")
        # 仍然保存信号历史(用于连续日追踪)
        if resonance["mid_count"] >= 1:
            save_signal_history(resonance)
        return

    # 盘中模式: 只做初筛, 不发邮件
    if not is_post_market:
        print(f"\n  📡 盘中初筛通过 ({resonance['mid_count']}只共振)")
        print(f"  ⏳ 等待盘后19:00份额确认...")
        save_signal_history(resonance)
        return

    # 盘后模式: 确认后才发邮件
    print(f"\n  ✅ 盘后确认 ({resonance['mid_count']}只共振)")

    if resonance["campaign_detected"]:
        print(f"  ⚡ 连续{resonance['consecutive_days']}日 → 战役级确认!")

    if not should_send():
        print(f"  ⏳ {MIN_GAP_HOURS}小时内已发过，跳过")
        save_signal_history(resonance)
        return

    print(f"  🚨 发送买入建议...")
    save_signal_history(resonance)
    send_buy_email(analysis, is_post_market=True)
    mark_sent()


if __name__ == "__main__":
    run()
